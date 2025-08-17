import json
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

from .forms import LessonForm, LessonGroupForm, SubtopicForm, TopicForm
from .models import Lesson, Topic, TopicGrade
from apps.authentication.models import CustomUser, Student, Parent
from apps.home.models import Subject, ClassRoom, QuarterGrader
from ..notification.models import Notification, GradingNotify


@login_required(login_url="/login/")
def lessons_list(request):
    user = request.user
    classroom_filter = request.GET.get('classroom', 'all')
    subject_filter = request.GET.get('subject', 'all')
    quarter_filter = request.GET.get('quarter', 'all')

    lessons = Lesson.objects.all()
    classrooms = ClassRoom.objects.all()
    quarters = [1, 2, 3, 4]

    if classroom_filter != 'all':
        subjects = Subject.objects.filter(teacher__classroom__name=classroom_filter)
        lessons = lessons.filter(subject__teacher__classroom__name=classroom_filter)
    else:
        subjects = []

    if subject_filter != "all":
        lessons = lessons.filter(subject__name=subject_filter)
    if quarter_filter != "all":
        lessons = lessons.filter(subject__name=subject_filter, quarter=quarter_filter)

    number_of_students = {}
    graded_percent_by_lesson = {}
    for lesson in lessons:
        # Total students for this subject
        total_students = Student.objects.filter(subjects=lesson.subject).count()
        number_of_students[lesson.title] = total_students

        # Students who have any TopicGrade for this lesson
        graded_count = (
            Student.objects
            .filter(subjects=lesson.subject, topicgrade__topic__lesson=lesson)
            .distinct()
            .count()
        )

        percent = int((graded_count / total_students) * 100) if total_students > 0 else 0
        graded_percent_by_lesson[lesson.id] = percent

    page = request.GET.get('page')
    paginator = Paginator(lessons, 5)
    page_obj = paginator.get_page(page)

    context = {'lessons': lessons,
               "number_of_students": number_of_students,
               "graded_percent_by_lesson": graded_percent_by_lesson,
               "classrooms": classrooms,
               "classroom_filter": classroom_filter,
               "subject_filter": subject_filter,
               "subjects": subjects,
               "quarter_filter": quarter_filter,
               "quarters": quarters,
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
    students = Student.objects.filter(subjects= lesson.subject, topicgrade__topic__lesson=lesson).distinct()

    student_grades = {}

    for student in students:
        s_key = student.user.id
        student_grades[s_key] = {"grade_total": round(lesson.calculate_student_grade(student), 1)}

        topic_grades = TopicGrade.objects.filter(
            student=student, topic__lesson=lesson
        ).values("topic_id", "grade", "comment")

        for grade in topic_grades:
            student_grades[s_key][grade["topic_id"]] = {
                "grade": grade["grade"],
                "comment": grade["comment"] or "",
            }

    context = {
        'lesson': lesson,
        'topics': topics,
        'students': students,
        'student_grades': student_grades,
        'student_grades_json': json.dumps(student_grades, ensure_ascii=False)
    }
    return render(request, 'lesson/lesson_details.html', context)


@login_required(login_url="/login/")
def create_topic(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if request.method == "POST":
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.lesson = lesson
            topic.parent = None
            topic.save()

            recalculate_topic_weights(lesson)
    return redirect('lesson:lesson_details', pk=pk)


@login_required(login_url="/login/")
def update_topic(request, pk):
    topic = get_object_or_404(Topic, pk = pk)
    lesson = topic.lesson

    if request.method == "POST":
        form = TopicForm(request.POST, instance=topic)
        if form.is_valid():
            form.save()
            return redirect('lesson:lesson_details', pk=lesson.id)
    else:
        form = TopicForm(instance=topic)

    total_topic_weights = 0
    topics = Topic.objects.filter(lesson=lesson, parent__isnull = True)
    for topic in topics:
        total_topic_weights += topic.topic_weight

    if total_topic_weights != 100:
        messages.warning(request, f"The total topic weight after editing is equal to {total_topic_weights}, but should be equal to 100.")


    return render(request, 'lesson/lesson_details.html', {
        'lesson': lesson,
        'form': form,
        'editing_topic': topic,
        'total_topic_weights': total_topic_weights
    })


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
    subtopic_weight_distribution(lesson = lesson)

    return redirect('lesson:lesson_details', pk=lesson_id)


def recalculate_topic_weights(lesson):
    topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)
    total_weight = sum(t.weight for t in topics)

    equal_share = round(100 / len(topics), 1) if topics else 0
    for t in topics:
        t.weight = equal_share
        t.save()
    return


@login_required(login_url="/login/")
def distribute_topic_weights_equally(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)

    calculated_weight = 100 / len(topics)
    for t in topics:
        t.weight = calculated_weight
        t.save()
    return redirect('lesson:lesson_details', pk=lesson.id)



@login_required(login_url="/login/")
def create_subtopic(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if request.method == "POST":
        form = SubtopicForm(request.POST, lesson=lesson)
        if form.is_valid():
            subtopic = form.save(commit=False)
            subtopic.lesson = lesson

            subtopic.save()

            subtopic_weight_distribution(lesson)


    return redirect('lesson:lesson_details', pk=pk)


@login_required(login_url="/login/")
def update_subtopic(request, pk):
    subtopic = get_object_or_404(Topic, pk=pk)
    lesson = subtopic.lesson

    if request.method == "POST":
        form = SubtopicForm(request.POST, instance=subtopic, lesson=lesson)
        if form.is_valid():
            form.save()
            return redirect('lesson:lesson_details', pk=lesson.id)
    else:
        form = SubtopicForm(instance=subtopic, lesson=lesson)

    total_subtopic_weights = 0
    parent = subtopic.parent
    subtopics = Topic.objects.filter(lesson=lesson, parent=parent)
    for subtopic in subtopics:
        total_subtopic_weights += subtopic.weight

    if total_subtopic_weights != 100:
        messages.warning(request, f"The total topic weight after editing is equal to {total_subtopic_weights}, but should be equal to 100.")


    return render(request, 'lesson/lesson_details.html', {
        'lesson': lesson,
        'form': form,
        'editing_subtopic': subtopic,
        'total_subtopic_weights': total_subtopic_weights
    })


def subtopic_weight_distribution(lesson):
    topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)

    for topic in topics:
        subtopics = Topic.objects.filter(parent=topic)
        if not subtopics.exists():
            continue

        equal_share = round(100 / len(subtopics), 1)
        for s in subtopics:
            s.weight = equal_share
            s.save()


@login_required(login_url="/login/")
def distribute_subtopic_weights_equally(request, lesson_id):
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
            scale_factor = 100 / len(topics)
            for s in subtopics:
                s.weight = scale_factor
                s.save()
    return redirect('lesson:lesson_details', pk=lesson.id)



@login_required(login_url="/login/")
def grading(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    students = Student.objects.filter(subjects = lesson.subject)
    topics = Topic.objects.filter(lesson = lesson)
    topic_grades = TopicGrade.objects.filter(topic__lesson=lesson, student__in=students)

    topic_grade_rows = (
        TopicGrade.objects
        .filter(topic__lesson=lesson, student__in=students)
        .select_related("student__user")
        .values("student__user_id", "topic_id", "grade", "comment")
    )

    topic_grade_map = {}
    has_grades = {}

    for grade in topic_grade_rows:
        student_id = grade["student__user_id"]
        key = f"{student_id}-{grade['topic_id']}"
        topic_grade_map[key] = {
            "grade": round(grade["grade"], 1),
            "comment": grade["comment"] or ""
        }
        has_grades[student_id] = True

    student_grades = {}
    for student in students:
        student_grades[student.user.id] = round(lesson.calculate_student_grade(student), 1)

    context = {
        'lesson': lesson,
        'students': students,
        'topics': topics,
        'topic_grade_map': json.dumps(topic_grade_map,ensure_ascii=False),
        'student_grades': student_grades,
        'has_grades': has_grades
    }
    return render(request, "lesson/grading.html", context)


@login_required(login_url="/login/")
def submit_all_topic_grades(request):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        lesson_id = request.POST.get('lesson_id')

        student = get_object_or_404(Student, user__id=student_id)
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        # Iterate through all top-level topics first
        for topic in lesson.topics.filter(parent__isnull=True):
            # Handle subtopics as checklist
            subtopics = list(topic.subtopics.all())
            for sub in subtopics:
                # Checkbox convention: presence means covered (1), absence means 0
                covered = request.POST.get(f'subtopic_{sub.id}_covered')
                grade_value = 100 if covered else 0

                # Preserve existing comment; no comment is posted from read-only UI
                tg, _created = TopicGrade.objects.update_or_create(
                    student=student,
                    topic=sub,
                    defaults={'grade': grade_value}
                )

            # Topic-level grade/comment
            # No topic comment is posted from read-only UI
            if subtopics:
                topic_grade_value = topic.calculate_subtopics_grade(student)
            else:
                # For topics without subtopics, use the topic checkbox
                covered = request.POST.get(f'topic_{topic.id}_covered')
                topic_grade_value = 100 if covered else 0

            TopicGrade.objects.update_or_create(
                student=student,
                topic=topic,
                defaults={'grade': topic_grade_value}
            )

        return redirect('lesson:grading', pk=lesson.id)
    return redirect('lesson:grading', pk=request.POST.get('lesson_id'))


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


@login_required(login_url="/login/")
def update_grade(request, pk=None):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        lesson_id = request.POST.get('lesson_id')

        student = get_object_or_404(Student, user__id=student_id)
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        for topic in lesson.topics.filter(parent__isnull=True):
            subtopics = list(topic.subtopics.all())
            for sub in subtopics:
                covered = request.POST.get(f'subtopic_{sub.id}_covered')
                grade_value = 100 if covered else 0

                TopicGrade.objects.update_or_create(
                    student=student,
                    topic=sub,
                    defaults={'grade': grade_value}
                )

            if subtopics:
                topic_grade_value = topic.calculate_subtopics_grade(student)
            else:
                covered = request.POST.get(f'topic_{topic.id}_covered')
                topic_grade_value = 100 if covered else 0

            TopicGrade.objects.update_or_create(
                student=student,
                topic=topic,
                defaults={'grade': topic_grade_value}
            )

        return redirect('lesson:lesson_details', pk=lesson.id)
    return redirect('lesson:lesson_details', pk=request.POST.get('lesson_id'))


@login_required(login_url="/login/")
def delete_grade(request, student_id, lesson_id):
    if request.method == 'POST':
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        topic_grades = TopicGrade.objects.filter(student_id=student_id, topic__lesson = lesson)
        topic_grades.delete()
        return redirect('lesson:grading', pk=lesson_id)
    return redirect('lesson:grading', pk=lesson_id)





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

