from pydoc_data.topics import topics

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from pycodestyle import continued_indentation

from .forms import LessonForm, LessonGroupForm
from .models import Lesson, Topic, TopicGrade
from apps.authentication.models import CustomUser, Student, Parent
from apps.home.models import Subject, ClassRoom, QuarterGrader
from ..notification.models import Notification, GradingNotify


@login_required(login_url="/login/")
def lessons_list(request):
    user = request.user
    classroom_filter = request.GET.get('classroom', 'all')
    subject_filter = request.GET.get('subject', 'all')

    lessons = Lesson.objects.all()
    classrooms = ClassRoom.objects.all()

    if classroom_filter != 'all':
        subjects = Subject.objects.filter(classroom__name=classroom_filter)
        lessons = lessons.filter(subject__classroom__name=classroom_filter)
    else:
        subjects = []

    if subject_filter != "all":
        lessons = lessons.filter(subject__name=subject_filter)

    number_of_students = {}
    for lesson in lessons:
        number_of_students[lesson.title] = Student.objects.filter(classroom=lesson.subject.teacher.classroom).count()

    page = request.GET.get('page')
    paginator = Paginator(lessons, 5)
    page_obj = paginator.get_page(page)

    context = {'lessons': lessons,
               "number_of_students": number_of_students,
               "classrooms": classrooms,
               "classroom_filter": classroom_filter,
               "subject_filter": subject_filter,
               "subjects": subjects,
               "page_obj": page_obj,
               'user': user
               }

    return render(request, 'lesson/lessons.html', context)


@login_required(login_url="/login/")
def lesson_create(request, subject_id=None):
    if request.method == "POST":
        form = LessonForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "👩‍🏫 Lesson created successfully!")
            return redirect("lesson:lessons")
    else:
        initial = {}
        if subject_id:
            try:
                subject = Subject.objects.get(pk=subject_id)
                initial['subject'] = subject
            except Subject.DoesNotExist:
                messages.error(request, "Subject not found!")
                return redirect("lesson:lessons")
        form = LessonForm(initial=initial)

    return render(request, "lesson/new_lesson.html", {"form": form})


@login_required(login_url="/login/")
def lesson_group_create(request):
    if request.method == 'POST':
        form = LessonGroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            return JsonResponse({
                "success": True,
                "group_id": group.id,
                "group_name": group.name
            })
        else:
            return JsonResponse({"success": False, "errors": form.errors})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url="/login/")
def lesson_details(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    topics = Topic.objects.filter(lesson=lesson, parent__isnull = True).prefetch_related('subtopics')
    students = Student.objects.filter(subjects= lesson.subject)
    student_grades = {}
    detailed_grades = {}

    for student in students:
        student_grades[student.user.id] = lesson.calculate_student_grade(student)
        topic_grades = TopicGrade.objects.filter(student=student, topic__lesson=lesson).select_related('topic')

        detailed_grades[student.user.id] = {}
        for tg in topic_grades:
            detailed_grades[student.user.id][tg.topic_id] = {
                "grade": round(tg.grade, 1),
                "comment": tg.comment
            }

    context = {
        'lesson': lesson,
        'topics': topics,
        'students': students,
        'student_grades': student_grades,
        "detailed_grades": detailed_grades,
    }
    return render(request, 'lesson/lesson_details.html', context)


@login_required(login_url="/login/")
def create_topic(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    title = request.POST.get('title')
    total_topics = Topic.objects.filter(parent__isnull = True, lesson = lesson).count()
    weight = request.POST.get('weight')
    topics = Topic.objects.filter(parent__isnull = True)

    current_weight_proportion = (total_topics * 100) / (total_topics + 1)
    max_new_topic_weight = 100 - current_weight_proportion


    if weight and int(weight) <= 100:
        weight = int(weight)
        new_proportion = 100 - weight
        for topic in topics:
            topic.weight = topic.weight / 100 * new_proportion
            topic.save()
    else:
        if weight:
            weight = int(weight)
        weight = max_new_topic_weight
        for topic in topics:
            topic.weight *= 100 / current_weight_proportion
            topic.save()

    topic = Topic.objects.create(lesson = lesson, title = title, weight = weight)

    context = {
        'lesson': lesson,
        'topic': topic
    }
    return redirect("lesson:lesson_details", pk=pk) # Do something with that


@login_required(login_url="/login/")
def update_topic(request, pk):
    topic = get_object_or_404(Topic, pk = pk)
    topic.title = request.POST.get('title')
    lesson = get_object_or_404(Lesson, pk=topic.lesson.id)

    total_topics = Topic.objects.filter(lesson = lesson, parent__isnull = True)
    total_weights = 0
    for i in total_topics:
        total_weights += i.weight

    weight = request.POST.get('weight')
    try:
        topic.weight = int(weight)
    except (TypeError, ValueError):
        topic.weight = 0

    topic.save()

    context = {
        'lesson': topic.lesson,
        'topic': topic,
        'parent': topic.parent,
    }

    return render(request, "lesson/lesson_details.html", context) # Do something with that


@login_required(login_url="/login/")
def distribute_topic_weights(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    topics = Topic.objects.filter(lesson = lesson, parent__isnull = True)
    total_weight = 0
    for i in topics:
        total_weight += i.weight

    if total_weight == 0:
        equal_share = round(100 / len(topics), 1) if topics else 0
        for t in topics:
            t.weight = equal_share
            t.save()
        return redirect('lesson:lesson_details', pk=lesson.id)

    factor = 100 / total_weight
    for t in topics:
        t.weight = round(t.weight * factor, 1)
        t.save()

    return redirect('lesson:lesson_details', pk=lesson.id)



@login_required(login_url="/login/")
def create_subtopic(request, pk):
    if request.method == "POST":
        lesson = get_object_or_404(Lesson, pk=pk)
        parent_id = request.POST.get("parent")
        print(parent_id)
        title = request.POST.get('title')
        weight = request.POST.get('weight') or 0

        if not parent_id:
            return redirect('lesson:lesson_details', pk=pk)

        parent_topic = get_object_or_404(Topic, id=parent_id, lesson=lesson)
        subtopic = Topic.objects.create(lesson=lesson, parent = parent_topic, title = title, weight = weight)

        context = {
            'lesson': lesson,
            'subtopic': subtopic
        }
        return redirect('lesson:lesson_details', pk=pk)


@login_required(login_url="/login/")
def delete_topic(request, pk):
    topic = get_object_or_404(Topic, pk = pk)
    lesson_id = topic.lesson.id
    topic.delete()

    lesson = get_object_or_404(Lesson, pk=lesson_id)
    topics = Topic.objects.filter(lesson=lesson, parent__isnull = True)
    for topic in topics:
        topic.weight = round(100 / (topics.count()), 1)
        topic.save()

    return redirect('lesson:lesson_details', pk=lesson_id)


@login_required(login_url="/login/")
def distribute_subtopic_weights(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)

    for topic in topics:
        subtopics = Topic.objects.filter(parent=topic)
        if not subtopics.exists():
            continue

        total_weight = sum(s.weight for s in subtopics)

        if total_weight == 0:
            equal_share = round(100 / len(subtopics), 1)
            for s in subtopics:
                s.weight = equal_share
                s.save()
        else:
            scale_factor = 100 / total_weight
            for s in subtopics:
                s.weight = round(s.weight * scale_factor, 1)
                s.save()

    return redirect('lesson:lesson_details', pk=lesson.id)


@login_required(login_url="/login/")
def grading(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    students = Student.objects.filter(subjects = lesson.subject)
    topics = Topic.objects.filter(lesson = lesson)
    topic_grades = TopicGrade.objects.filter(topic__lesson=lesson, student__in=students)

    topic_grade_map = {}
    for tg in topic_grades:
        topic_grade_map[f"{tg.student_id}_{tg.topic_id}"] = {
            "grade": round(tg.grade, 1),
            "comment": tg.comment
        }

    student_grades = {}
    for student in students:
        student_grades[student.user.id] = lesson.calculate_student_grade(student)

    context = {
        'lesson': lesson,
        'students': students,
        'topics': topics,
        'topic_grade_map': topic_grade_map,
        'student_grades': student_grades
    }
    return render(request, "lesson/grading.html", context)

@login_required(login_url="/login/")
def submit_all_topic_grades(request):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        print(student_id)
        lesson_id = request.POST.get('lesson_id')

        student = get_object_or_404(Student, user__id=student_id)
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        for topic in lesson.topics.all():
            for sub in topic.subtopics.all():
                grade = request.POST.get(f'subtopic_{sub.id}_grade', '0') or '0'
                comment = request.POST.get(f'subtopic_{sub.id}_comment', '')

                TopicGrade.objects.update_or_create(
                    student=student,
                    topic=sub,
                    defaults={
                        'grade': grade,
                        'comment': comment
                    }
                )

            topic_comment = request.POST.get(f'topic_{topic.id}_comment', '')
            TopicGrade.objects.update_or_create(
                student=student,
                topic=topic,
                defaults={
                    'grade': topic.calculate_subtopics_grade(student),
                    'comment': topic_comment
                }
            )
    return redirect('lesson:lesson_details', pk=lesson.id)

@login_required(login_url="/login/")
def update_grade(request):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        lesson_id = request.POST.get('lesson_id')

        student = get_object_or_404(Student, user__id=student_id)
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        for topic in lesson.topics.all():
            for sub in topic.subtopics.all():
                grade = request.POST.get(f'subtopic_{sub.id}_grade', '0') or '0'
                comment = request.POST.get(f'subtopic_{sub.id}_comment', '')

                TopicGrade.objects.update_or_create(
                    student=student,
                    topic=sub,
                    defaults={
                        'grade': grade,
                        'comment': comment
                    }
                )

            topic_comment = request.POST.get(f'topic_{topic.id}_comment', '')
            TopicGrade.objects.update_or_create(
                student=student,
                topic=topic,
                defaults={
                    'grade': topic.calculate_subtopics_grade(student),
                    'comment': topic_comment
                }
            )
    return redirect('lesson:lesson_details', pk=lesson.id)


@login_required(login_url="/login/")
def delete_grade(request, student_id, lesson_id):
    if request.method == 'DELETE':
        student_id = request.POST.get('student_id')
        lesson_id = request.POST.get('lesson_id')
        topics = Topic.objects.filter(lesson=lesson_id)
        topic_grades = TopicGrade.objects.filter(student=student_id, topic__in=topics)
        topic_grades.delete()
    return redirect('lesson:grading', pk=lesson_id)


@login_required(login_url="/login/")
def display_grade(request, student_id, lesson_id):
    student = get_object_or_404(Student, user__id=student_id)
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    topics = Topic.objects.filter(lesson=lesson)
    topic_grades = TopicGrade.objects.filter(student=student, topic__lesson=lesson)

    all_grades = {}
    for tg in topic_grades:
        all_grades[tg.topic_id] = tg.grade
    context = {
        'topics': topics,
        'all_grades':all_grades
    }

    return render(request,'lesson:lesson_details', pk=lesson.id)


#EMAIL SENDING SIGNAL ------------------------------------------

#
# @receiver(pre_save, sender=StudentGrade)
# def grading_pre_save_email(sender, instance, **kwargs):
#     lesson = instance.lesson
#     target_student = instance.student
#     if isinstance(target_student, CustomUser):
#         try:
#             target_student = Student.objects.get(user=target_student)
#         except Student.DoesNotExist:
#             return
#
#     student_user = target_student.user
#
#     try:
#         parent = Parent.objects.get(student_id=student_user.id)
#         parent_user = parent.user
#     except Parent.DoesNotExist:
#         parent = None
#         parent_user = None
#
#     subject = f"Уведомление об обновлении оценки по предмету: {lesson.title}"
#     html_message = render_to_string(
#         "email/grade_student_email.html",
#         {"student": target_student, "lesson": lesson}
#     )
#     plain_message = strip_tags(html_message)
#
#     send_mail(
#         subject=subject,
#         message=plain_message,
#         from_email=settings.DEFAULT_FROM_EMAIL,
#         recipient_list=[student_user.email],
#         html_message=html_message
#     )
#
#     notification = Notification.objects.create(user=student_user, action='grading')
#
#     if parent and parent_user:
#         parent_subject = "Обновление оценки по предмету"
#         html_parent_message = render_to_string(
#             "email/grade_parent_email.html",
#             {"parent": parent_user, "lesson": lesson}
#         )
#         plain_parent_message = strip_tags(html_parent_message)
#
#         send_mail(
#             subject=parent_subject,
#             message=plain_parent_message,
#             from_email=settings.DEFAULT_FROM_EMAIL,
#             recipient_list=[parent_user.email],
#             html_message=html_parent_message
#         )
#
#         GradingNotify.objects.create(
#             notification=notification,
#             parent=parent,
#             lesson=lesson
#         )
#     else:
#         GradingNotify.objects.create(
#             notification=notification,
#             lesson=lesson
#         )


#COMMENT Templates ----------------------------------------------------------

# @login_required(login_url="/login/")
# def comment_template_create(request):
#     if request.method == 'POST':
#         from_points = request.POST.get('from_points')
#         to_points = request.POST.get('to_points')
#         comment_text = request.POST.get('comment_text')
#         lesson_id = request.POST.get('lesson_id')
#
#         try:
#             from_points = int(from_points)
#             to_points = int(to_points)
#
#             if from_points > to_points:
#                 messages.error(request, "Начальное значение баллов не может быть больше конечного!")
#                 return redirect(request.META.get('HTTP_REFERER', '/'))
#
#             lesson = get_object_or_404(Lesson, id=lesson_id) if lesson_id else None
#             comment = Comment.objects.create(
#                 lesson=lesson,
#                 from_points=from_points,
#                 to_points=to_points,
#                 comment_text=comment_text
#             )
#
#             messages.success(request, "Шаблон комментария успешно создан!")
#             return redirect(request.META.get('HTTP_REFERER', '/'))
#
#         except ValueError:
#             messages.error(request, "Пожалуйста, введите корректные числовые значения для баллов!")
#             return redirect(request.META.get('HTTP_REFERER', '/'))
#         except Exception as e:
#             messages.error(request, f"Произошла ошибка при создании шаблона: {str(e)}")
#             return redirect(request.META.get('HTTP_REFERER', '/'))
#
#     return redirect(request.META.get('HTTP_REFERER', '/'))
#
#
# @login_required(login_url="/login/")
# def comment_template_update(request, comment_id):
#     comment = get_object_or_404(Comment, id=comment_id)
#
#     if request.method == 'POST':
#         from_points = request.POST.get('from_points')
#         to_points = request.POST.get('to_points')
#         comment_text = request.POST.get('comment_text')
#
#         try:
#             from_points = int(from_points)
#             to_points = int(to_points)
#
#             if from_points > to_points:
#                 messages.error(request, "Начальное значение баллов не может быть больше конечного!")
#                 return redirect(request.META.get('HTTP_REFERER', '/'))
#
#             comment.from_points = from_points
#             comment.to_points = to_points
#             comment.comment_text = comment_text
#             comment.save()
#
#             messages.success(request, "Шаблон комментария успешно обновлен!")
#             return redirect(request.META.get('HTTP_REFERER', '/'))
#
#         except ValueError:
#             messages.error(request, "Пожалуйста, введите корректные числовые значения для баллов!")
#             return redirect(request.META.get('HTTP_REFERER', '/'))
#         except Exception as e:
#             messages.error(request, f"Произошла ошибка при обновлении шаблона: {str(e)}")
#             return redirect(request.META.get('HTTP_REFERER', '/'))
#
#     return redirect(request.META.get('HTTP_REFERER', '/'))
#
#
# @login_required(login_url="/login/")
# def comment_template_delete(request, comment_id):
#     comment = get_object_or_404(Comment, id=comment_id)
#
#     try:
#         comment.delete()
#         messages.success(request, "Шаблон комментария успешно удален!")
#     except Exception as e:
#         messages.error(request, f"Произошла ошибка при удалении шаблона: {str(e)}")
#
#     return redirect(request.META.get('HTTP_REFERER', '/'))

