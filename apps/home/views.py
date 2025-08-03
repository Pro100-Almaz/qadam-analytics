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

from apps.authentication.models import CustomUser, PsychologicalStateTemplates, PsychologicalState, \
    Teacher, Student, Supervisor, Parent
from apps.home.models import ClassRoom
from apps.notification.models import PsychologicalNotify


@login_required(login_url="/login/")
def index(request):
    context = {'segment': 'index'}
    return render(request, 'home/index.html', context)

@login_required(login_url="/login/")
def main_page(request):
    total_students = Student.objects.all().count()
    total_teachers = Teacher.objects.all().count()
    total_classes = ClassRoom.objects.all().count()

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
    student = None
    if user.is_parent():
        try:
            parent = Parent.objects.select_related('student').get(user=user)
            student = parent.student
        except Parent.DoesNotExist:
            pass
    teacher = Teacher.objects.filter(user=user).first() if user.is_teacher() else None

    classrooms = ClassRoom.objects.all()

    context = {
        'user': user,
        'student': student,
        'teacher': teacher,
        'classrooms': classrooms,
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
        user.phone_number = request.POST.get('phone_number')
        user.date_of_birth = request.POST.get('date_of_birth')
        user.occupation = request.POST.get('occupation')
        user.address = request.POST.get('address')
        
        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
        
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
    if avatar:
        email_msg.attach(avatar.name, avatar.read(), avatar.content_type)

    email_msg.send()
    print("Supervisor:", supervisor)
    print("Supervisor Email:", supervisor.user.email)
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


@login_required(login_url="/login/")
def teachers_list(request):
    teachers = Teacher.objects.all()

    page = request.GET.get('page')
    paginator = Paginator(teachers, 5)
    page_obj = paginator.get_page(page)

    context = {'teachers': teachers, "page_obj": page_obj}
    return render(request, 'home/teachers.html', context)


@login_required(login_url="/login/")
def create_psychological_state(request, pk):
    if request.method == "POST":
        name = request.POST.get('state_name')
        comment = request.POST.get('comment')
        score = request.POST.get('star_rating')
        student_id = request.POST.get('student_id')

        try:
            student = Student.objects.get(pk=student_id)
        except Student.DoesNotExist:
            messages.error(request, f"Student with id={student_id} does not exist.")
            return redirect('students')

        if not PsychologicalStateTemplates.objects.filter(name=name).exists():
            PsychologicalStateTemplates.objects.create(name=name, comment=comment)

        PsychologicalState.objects.create(name=name,
                                          comment=comment,
                                          score = score,
                                          student=student,
                                          added_by=request.user)

    return redirect('student_details', pk=pk)

@login_required(login_url="/login/")
def delete_psychological_state(request, pk):
    if request.method == "POST":
        try:
            state = PsychologicalState.objects.get(pk=pk, student__user=request.user)
            state.delete()
            return JsonResponse({'status': 'success'})
        except PsychologicalState.DoesNotExist:
            return JsonResponse({'status': 'not_found'}, status=404)
    return JsonResponse({'error': 'Only POST method allowed'}, status=405) # @require_POST decorator kosu norm ba?, is it legal?


@receiver(pre_save, sender=PsychologicalState)
def psycho_state_pre_save(sender, instance, **kwargs):
    added_by_user = instance.added_by
    target_student = instance.student
    student_custom_user = target_student.user

    try:
        parent = Parent.objects.get(student_id=student_custom_user.id)
    except Parent.DoesNotExist:
        parent = None


    subject = "Уведомление об обновлении отчета о Психическом Состоянии Студента"
    html_message = render_to_string("email/psychological_state_student_email.html",
                                   {"student": target_student, "adder": added_by_user})
    plain_message = strip_tags(html_message)
    from_mail = settings.DEFAULT_FROM_EMAIL
    to_mail = [student_custom_user.email]

    send_mail(
        subject=subject,
        message=plain_message,
        from_email=from_mail,
        recipient_list=to_mail,
        html_message=html_message
    )

    if parent:
        parent_user = parent.user

        subject_parent = "Psychological State Update"
        html_message_parent = render_to_string("email/psychological_state_parent_email.html",
                                               {"parent": parent_user, "adder": added_by_user})
        plain_message_parent = strip_tags(html_message_parent)
        from_mail_parent = settings.DEFAULT_FROM_EMAIL
        to_mail_parent = [parent_user.email]

        send_mail(
            subject=subject_parent,
            message=plain_message_parent,
            from_email=from_mail_parent,
            recipient_list=to_mail_parent,
            html_message=html_message_parent
        )

        from apps.notification.models import Notification, PsychologicalNotify
        notification = Notification.objects.create(user=student_custom_user, action='psychological_state')
        PsychologicalNotify.objects.create(notification=notification, parent=parent, psychologist=added_by_user)

    else:
        from apps.notification.models import Notification, PsychologicalNotify
        notification = Notification.objects.create(user=target_student, action='psychological_state')
        PsychologicalNotify.objects.create(notification=notification, psychologist=added_by_user)





@login_required(login_url="/login/")
def create_psychological_state_template(request, pk):
    if request.method == "POST":
        name = request.POST.get('template_name')
        comment = request.POST.get('template_comment')

        if not PsychologicalStateTemplates.objects.filter(name=name).exists():
            PsychologicalStateTemplates.objects.create(name=name, comment=comment)

        PsychologicalState.objects.create(name=name, comment=comment)

    return redirect('student_details', pk=pk)
