from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView, ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from .permissions import IsAdminRole
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import CustomUser, SchoolGroup
from apps.authentication.services import AccountService

from .serializers import (
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    UserUpdateSerializer,
    AvatarUploadSerializer,
    ForgetPasswordSerializer,
    VerificationCodeSerializer,
    PasswordChangeSerializer,
    ResetPasswordSerializer,
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


class LogoutAPIView(APIView):
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


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

    def post(self, request):
        serializer = ForgetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username']

        user = CustomUser.objects.filter(username=username).first()
        if not user:
            return Response(
                {'detail': 'Пользователь не найден'},
                status=status.HTTP_404_NOT_FOUND,
            )

        service = AccountService()
        signed_code = service.send_verification_code(user)
        return Response({
            'username': user.username,
            'signed_code': signed_code,
        })


class VerificationCodeAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, username, signed_code):
        serializer = VerificationCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entered = serializer.validated_data['verification_code']

        ok, error = AccountService.check_verification_code(signed_code, entered)
        if ok:
            return Response({
                'username': username,
                'signed_code': signed_code,
                'verified': True,
            })
        return Response(
            {'detail': error or 'Неверный код.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PasswordChangeAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, username, signed_code):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = CustomUser.objects.filter(username=username).first()
        if not user:
            return Response(
                {'detail': 'Пользователь не найден'},
                status=status.HTTP_404_NOT_FOUND,
            )

        pw1 = serializer.validated_data['password1']
        pw2 = serializer.validated_data['password2']
        ok, error = AccountService().change_password_with_code(user, pw1, pw2)
        if ok:
            return Response({'detail': 'Пароль успешно изменен!'})
        return Response(
            {'detail': error or 'Ошибка'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ResetPasswordAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, uidb64, token):
        user = AccountService.validate_reset_link(uidb64, token)
        if not user:
            return Response(
                {'detail': 'Invalid link or token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        AccountService.set_new_password(user, serializer.validated_data['new_password'])
        return Response({'detail': 'Пароль успешно изменен!'})


class SchoolGroupListAPIView(ListAPIView):
    permission_classes = [AllowAny]
    queryset = SchoolGroup.objects.all()
    serializer_class = SchoolGroupSerializer
    pagination_class = None


# class SchoolGroupDetailAPIView(RetrieveAPIView):
#     permission_classes = [AllowAny]
#     queryset = SchoolGroup.objects.all()
#     serializer_class = SchoolGroupSerializer
