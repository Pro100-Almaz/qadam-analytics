from django import template
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail, EmailMultiAlternatives
from django.core.paginator import Paginator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.http import HttpResponseRedirect, JsonResponse, HttpResponseNotAllowed
from django.template.loader import render_to_string
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.html import strip_tags

from core.decorators import role_required
from core.permissions import can_access_student, permission_denied_response
from apps.authentication.models import (
    CustomUser, PsychologicalStateTemplates, PsychologicalState,
    Teacher, Student, Supervisor, Parent, MAX_AVATAR_SIZE_MB, MAX_AVATAR_SIZE_BYTES
)
from apps.home.models import ClassGroup
from apps.notification.models import PsychologicalNotify


@login_required(login_url="/login/")
def index(request):
    context = {'segment': 'index'}
    return render(request, 'home/index.html', context)

@login_required(login_url="/login/")
def main_page(request):
    total_students = Student.objects.all().count()
    total_teachers = Teacher.objects.all().count()
    total_classes = ClassGroup.objects.all().count()

    if Teacher.objects.filter(user=request.user).exists():
        template_name = 'teacher.html'
    elif Student.objects.filter(user=request.user).exists():
        template_name = 'student.html'
    else:
        template_name = 'default.html'

    context = {
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_classes': total_classes,
    }

    return render(request, 'main_page/' + template_name, context)

def profile(request):
    user = request.user
    students = None
    if user.is_parent():
        try:
            parent = Parent.objects.prefetch_related('students').get(user=user)
            students = parent.students.all()
        except Parent.DoesNotExist:
            pass
    teacher = Teacher.objects.filter(user=user).first() if user.is_teacher() else None

    class_groups = ClassGroup.objects.all()

    context = {
        'user': user,
        'students': students,
        'teacher': teacher,
        'class_groups': class_groups,
    }
    return render(request, 'home/profile.html', context)

@login_required(login_url="/login/")
def profile_update(request):
    if request.method == "POST":
        user = request.user

        # Update basic user information
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        user.phone_number = request.POST.get('phone_number') or None
        user.address = request.POST.get('address') or None

        # Handle date_of_birth - convert empty string to None
        date_of_birth = request.POST.get('date_of_birth')
        user.date_of_birth = date_of_birth if date_of_birth else None
        
        # Handle avatar upload with size validation
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']
            if avatar_file.size > MAX_AVATAR_SIZE_BYTES:
                messages.error(
                    request,
                    f"Avatar file size must be less than {MAX_AVATAR_SIZE_MB}MB. "
                    f"Your file: {avatar_file.size / (1024 * 1024):.2f}MB"
                )
                return redirect('profile')
            user.avatar = avatar_file

        try:
            user.save()
            messages.success(request, "Profile updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}")
        
        return redirect('profile')
    
    return redirect('profile')

@login_required(login_url="/login/")
def profile_edit_request(request):
    supervisor = Supervisor.objects.all().first()
    user = request.user

    username = request.POST.get('username')
    email = request.POST.get('email')
    first_name = request.POST.get('first_name')
    last_name = request.POST.get('last_name')
    phone_number = request.POST.get('phone_number')
    date_of_birth = request.POST.get('date_of_birth')
    address = request.POST.get('address')
    occupation = request.POST.get('occupation')
    classroom = request.POST.get('classroom')
    academic_degree = request.POST.get('academic_degree')
    employment_type = request.POST.get('employment_type')
    gender = request.POST.get('gender')
    working_hours = request.POST.get('working_hours')
    avatar = request.FILES.get('avatar')

    # Avatar can be updated directly without approval (with size validation)
    if avatar:
        if avatar.size > MAX_AVATAR_SIZE_BYTES:
            messages.error(
                request,
                f"Avatar file size must be less than {MAX_AVATAR_SIZE_MB}MB. "
                f"Your file: {avatar.size / (1024 * 1024):.2f}MB"
            )
        else:
            user.avatar = avatar
            user.save(update_fields=['avatar'])
            messages.success(request, "Profile picture updated successfully!")

    subject = "Запрос от пользователя на изменения персональных данных"
    html_message = render_to_string("email/profile_edit_request.html",
                                    {
                                        "sender_username": username,
                                        "sender_email": email,
                                        "sender_first_name": first_name,
                                        "sender_last_name": last_name,
                                        "sender_phone_number": phone_number,
                                        "sender_date_of_birth": date_of_birth,
                                        "sender_address": address,
                                        "sender_occupation": occupation,
                                        "sender_classroom": classroom,
                                        "sender_academic_degree": academic_degree,
                                        "sender_employment_type": employment_type,
                                        "sender_gender": gender,
                                        "sender_working_hours": working_hours,
                                        "sender": user,
                                        "supervisor": supervisor
                                    })
    plain_message = strip_tags(html_message)
    from_mail = settings.EMAIL_HOST_USER
    to_mail = [supervisor.user.email]

    email_msg = EmailMultiAlternatives(subject, plain_message, from_mail, to_mail)
    email_msg.attach_alternative(html_message, "text/html")

    email_msg.send()
    messages.success(request, "Your profile change request has been sent to the principal.")
    return redirect("profile")


@login_required(login_url="/login/")
def pages(request):
    context = {}
    try:
        load_template = request.path.split('/')[-1]
        if load_template == 'admin':
            return HttpResponseRedirect(reverse('admin:index'))
        context['segment'] = load_template
        return render(request, 'home/' + load_template, context)
    except template.TemplateDoesNotExist:
        return render(request, 'home/page-404.html', context)
    except:
        return render(request, 'home/page-500.html', context)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def teachers_list(request):
    teachers = Teacher.objects.all()

    page = request.GET.get('page')
    paginator = Paginator(teachers, 5)
    page_obj = paginator.get_page(page)

    context = {'teachers': teachers, "page_obj": page_obj}
    return render(request, 'home/teachers.html', context)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def create_psychological_state(request, pk):
    # Get the student first for permission check
    try:
        student = Student.objects.get(pk=pk)
    except Student.DoesNotExist:
        messages.error(request, f"Student with id {pk} does not exist.")
        return redirect("students")

    # Object-level permission: verify user can access this student
    if not can_access_student(request.user, student):
        return permission_denied_response("You can only manage psychological states for students you have access to.")

    if request.method == "POST":
        if request.POST.get("_method") == "DELETE":
            state_id = request.POST.get("state_id")
            try:
                state = PsychologicalState.objects.get(pk=state_id, student_id=pk)
                state.delete()
                messages.success(request, "Psychological state was deleted!")
                return redirect("student_details", pk=student.user.id)

            except PsychologicalState.DoesNotExist:
                messages.error(request, f"Psychological state with id {state_id} does not exist.")
                return redirect("student_details", pk=pk)

        name = request.POST.get("state_name")
        comment = request.POST.get("comment")
        score = request.POST.get("star_rating")

        if not PsychologicalStateTemplates.objects.filter(name=name).exists():
            PsychologicalStateTemplates.objects.create(name=name, comment=comment)

        PsychologicalState.objects.create(
            name=name,
            comment=comment,
            score=score,
            student=student,
            added_by=request.user,
        )
        messages.success(request, "Эмоциональный благосостояние успешно добавлено!")
        return redirect("student_details", pk=student.user.id)

    return redirect("students")


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def create_psychological_state_template(request, pk):
    if request.method == "POST":
        name = request.POST.get('template_name')
        comment = request.POST.get('template_comment')

        if not PsychologicalStateTemplates.objects.filter(name=name).exists():
            PsychologicalStateTemplates.objects.create(name=name, comment=comment)

        PsychologicalState.objects.create(name=name, comment=comment)

    return redirect('student_details', pk=pk)


@login_required(login_url="/login/")
def api_class_groups(request):
    """API endpoint to get class groups for a given academic year."""
    year_id = request.GET.get('year')

    if not year_id:
        return JsonResponse({'error': 'Year parameter required'}, status=400)

    try:
        class_groups = ClassGroup.objects.filter(
            academic_year_id=year_id
        ).order_by('grade_level__number', 'letter')

        data = {
            'class_groups': [
                {'id': cg.id, 'name': str(cg)}
                for cg in class_groups
            ]
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
