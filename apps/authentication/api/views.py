import logging
import time

from django.core.cache import cache
from django.core.signing import Signer
from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView, RetrieveAPIView, ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.api.permissions import IsAdminRole
from apps.authentication.models import CustomUser, SchoolGroup
from apps.authentication.services import AccountService
from core.error_messages import (
    USER_NOT_FOUND, REFRESH_TOKEN_REQUIRED, LOGOUT_FAILED,
    NO_ACTIVE_RESET, TOO_MANY_ATTEMPTS, INVALID_CODE,
    RESET_TOKEN_REQUIRED, INVALID_TOKEN, INVALID_LINK,
    PASSWORD_CHANGED, GENERIC_ERROR,
)

from apps.authentication.api.serializers import (
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    UserUpdateSerializer,
    AvatarUploadSerializer,
    ForgetPasswordSerializer,
    VerificationCodeSerializer,
    PasswordChangeSerializer,
    ResetPasswordSerializer,
    PublicSchoolGroupSerializer,
    SchoolGroupSerializer,
)


def _get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class LoginAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        tokens = _get_tokens_for_user(user)
        return Response({
            'tokens': tokens,
            'user': UserSerializer(user).data,
        })


class RegisterAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


logger = logging.getLogger(__name__)


class LogoutAPIView(APIView):
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'detail': REFRESH_TOKEN_REQUIRED},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            pass
        except Exception:
            logger.exception('Failed to blacklist refresh token during logout')
            return Response(
                {'detail': LOGOUT_FAILED},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class CurrentUserAPIView(RetrieveUpdateAPIView):
    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return UserUpdateSerializer
        return UserSerializer


class AvatarUploadAPIView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.avatar = serializer.validated_data['avatar']
        request.user.save(update_fields=['avatar'])
        return Response({'avatar': request.user.avatar.url})


class ForgetPasswordAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = ForgetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username']

        user = CustomUser.objects.filter(username=username).first()
        if not user:
            return Response(
                {'detail': USER_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )

        service = AccountService()
        signed_code = service.send_verification_code(user)

        cache.set(
            f'pwd_reset:{username}',
            {'signed_code': signed_code, 'attempts': 0},
            timeout=600,
        )
        return Response({
            'message': 'Verification code sent',
            'username': user.username,
        })


class VerificationCodeAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'verify_code'

    def post(self, request):
        serializer = VerificationCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username']
        entered = serializer.validated_data['verification_code']

        cache_key = f'pwd_reset:{username}'
        reset_data = cache.get(cache_key)
        if not reset_data:
            return Response(
                {'detail': NO_ACTIVE_RESET},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if reset_data['attempts'] >= 5:
            cache.delete(cache_key)
            return Response(
                {'detail': TOO_MANY_ATTEMPTS},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        ok, error = AccountService.check_verification_code(
            reset_data['signed_code'], entered,
        )
        if not ok:
            reset_data['attempts'] += 1
            cache.set(cache_key, reset_data, timeout=600)
            remaining = 5 - reset_data['attempts']
            return Response(
                {'detail': error or INVALID_CODE, 'attempts_remaining': remaining},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache.delete(cache_key)
        signer = Signer()
        reset_token = signer.sign(f'{username}:{int(time.time())}')
        cache.set(f'pwd_token:{reset_token}', username, timeout=300)

        return Response({
            'token': reset_token,
            'verified': True,
        })


class PasswordChangeAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data.get('token')
        if not token:
            return Response(
                {'detail': RESET_TOKEN_REQUIRED},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_key = f'pwd_token:{token}'
        username = cache.get(token_key)
        if not username:
            return Response(
                {'detail': INVALID_TOKEN},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = CustomUser.objects.filter(username=username).first()
        if not user:
            return Response(
                {'detail': USER_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )

        pw1 = serializer.validated_data['password1']
        pw2 = serializer.validated_data['password2']
        ok, error = AccountService().change_password_with_code(user, pw1, pw2)
        if not ok:
            return Response(
                {'detail': error or GENERIC_ERROR},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache.delete(token_key)
        OutstandingToken.objects.filter(user=user).delete()
        return Response({'detail': PASSWORD_CHANGED})


class ResetPasswordAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, uidb64, token):
        user = AccountService.validate_reset_link(uidb64, token)
        if not user:
            return Response(
                {'detail': INVALID_LINK},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        AccountService.set_new_password(user, serializer.validated_data['new_password'])
        return Response({'detail': PASSWORD_CHANGED})


class SchoolGroupListAPIView(ListAPIView):
    permission_classes = [AllowAny]
    queryset = SchoolGroup.objects.all()
    serializer_class = PublicSchoolGroupSerializer
    pagination_class = None


class SchoolGroupDetailAPIView(RetrieveAPIView):
    permission_classes = [AllowAny]
    queryset = SchoolGroup.objects.all()
    serializer_class = PublicSchoolGroupSerializer
