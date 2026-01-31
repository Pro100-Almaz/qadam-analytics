from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.http import JsonResponse

from apps.home.services import students as students_service


@login_required
def api_upload_student_avatar(request, pk : int):
    if request.method == 'POST' and request.FILES['avatar']:
        saved_avatar_url = students_service.change_student_avatar(pk, request.FILES['avatar'])

        return JsonResponse({'status' : 'success', 'image_url' : saved_avatar_url})

    return JsonResponse({'status' : 'fail'}, status = 400)