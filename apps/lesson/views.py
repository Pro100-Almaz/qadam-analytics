import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from core.decorators import role_required
from core.permissions import (
    can_modify_lesson, can_access_lesson, can_grade_student,
    permission_denied_response, is_admin_role
)
from .forms import LessonForm, LessonGroupForm, SubtopicForm, TopicForm
from .models import Lesson, Topic, TopicGrade, MergedLessonComment
from apps.authentication.models import CustomUser, Student, Parent
from apps.home.models import Subject, ClassGroup, QuarterGrader, Enrollment
from apps.notification.models import Notification, GradingNotify


@login_required(login_url="/login/")
def lessons_list(request):
    user = request.user
    class_group_filter = request.GET.get('class_group', 'all')
    subject_filter = request.GET.get('subject', 'all')
    quarter_filter = request.GET.get('quarter', 'all')

    lessons = Lesson.objects.select_related('offering', 'offering__subject', 'offering__class_group').all()
    class_groups = ClassGroup.objects.all()
    quarters = [1, 2, 3, 4]

    if class_group_filter != 'all':
        lessons = lessons.filter(offering__class_group_id=class_group_filter)
        subjects = Subject.objects.filter(offerings__class_group_id=class_group_filter).distinct()
    else:
        subjects = Subject.objects.all()

    if subject_filter != "all":
        lessons = lessons.filter(offering__subject__name=subject_filter)
    if quarter_filter != "all":
        lessons = lessons.filter(quarter=quarter_filter)

    number_of_students = {}
    graded_percent_by_lesson = {}
    for lesson in lessons:
        # Total students enrolled in this offering's class group
        from apps.home.models import Enrollment
        total_students = Enrollment.objects.filter(
            class_group=lesson.offering.class_group,
            status='active'
        ).count() if lesson.offering else 0
        number_of_students[lesson.title] = total_students

        # Students who have any TopicGrade for this lesson
        graded_count = (
            Student.objects
            .filter(topicgrade__topic__lesson=lesson)
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
               "class_groups": class_groups,
               "class_group_filter": class_group_filter,
               "subject_filter": subject_filter,
               "subjects": subjects,
               "quarter_filter": quarter_filter,
               "quarters": quarters,
               "page_obj": page_obj,
               'user': user
               }

    return render(request, 'lesson/lessons.html', context)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def lesson_create(request, subject_id=None):
    from apps.home.models import SubjectOffering, TeachingAssignment
    from apps.authentication.models import Teacher

    # Determine available offerings for the current user
    user = request.user
    if user.is_admin() or user.is_principal() or user.is_manager():
        available_offerings = SubjectOffering.objects.select_related('subject', 'class_group', 'academic_year')
    elif user.is_teacher() or user.is_homeroom_teacher():
        try:
            teacher = Teacher.objects.get(user=user)
            offering_ids = TeachingAssignment.objects.filter(
                teacher=teacher
            ).values_list('offering_id', flat=True)
            available_offerings = SubjectOffering.objects.filter(
                id__in=offering_ids
            ).select_related('subject', 'class_group', 'academic_year')
        except Teacher.DoesNotExist:
            available_offerings = SubjectOffering.objects.none()
    else:
        available_offerings = SubjectOffering.objects.none()

    if request.method == "POST":
        form = LessonForm(request.POST)
        form.fields['offering'].queryset = available_offerings
        if form.is_valid():
            form.save()
            messages.success(request, "Урок успешно создан!")
            offering = form.cleaned_data['offering']
            return redirect("subject_details", pk=offering.subject.pk)
    else:
        initial = {}
        if subject_id:
            # Pre-select the first offering for this subject
            offering = available_offerings.filter(subject_id=subject_id).first()
            if offering:
                initial['offering'] = offering
            else:
                messages.error(request, "Предмет не найден или у вас нет доступа!")
                return redirect("lesson:lessons")
        form = LessonForm(initial=initial)
        form.fields['offering'].queryset = available_offerings

    return render(request, "lesson/new_lesson.html", {"form": form})

@role_required('teacher', 'admin', 'supervisor')
def lesson_delete(request, lesson_id):
    if request.method == "POST":
        lesson = Lesson.objects.get(pk=lesson_id)
        lesson.delete()
        messages.success(request, "Lesson deleted successfully!")
    return redirect("lesson:lessons")


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
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
    students = Student.objects.filter(
        enrollments__class_group=lesson.offering.class_group,
        enrollments__academic_year=lesson.offering.academic_year,
        enrollments__status='active'
    ).distinct()

    student_grades = {}

    for student in students:
        s_key = student.user.id
        student_grades[s_key] = {"grade_total": (round(lesson.calculate_student_grade(student), 1))}

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


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def create_topic(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only create topics for your own lessons.")

    if request.method == "POST":
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.lesson = lesson
            topic.parent = None
            # Auto-assign order: next available order number
            max_order = Topic.objects.filter(lesson=lesson, parent__isnull=True).aggregate(
                max_order=models.Max('order')
            )['max_order'] or 0
            topic.order = max_order + 1
            topic.save()

            recalculate_topic_weights(lesson)
    return redirect('lesson:lesson_details', pk=pk)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def update_topic(request, pk):
    topic = get_object_or_404(Topic, pk = pk)
    lesson = topic.lesson

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only update topics for your own lessons.")

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
        total_topic_weights += topic.weight

    if total_topic_weights != 100:
        messages.warning(request, f"The total topic weight after editing is equal to {total_topic_weights}, but should be equal to 100.")


    return render(request, 'lesson/lesson_details.html', {
        'lesson': lesson,
        'form': form,
        'editing_topic': topic,
        'total_topic_weights': total_topic_weights
    })


@role_required('teacher', 'admin', 'supervisor')
def delete_topic(request, pk):
    topic = get_object_or_404(Topic, pk = pk)
    lesson = topic.lesson

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only delete topics for your own lessons.")

    lesson_id = lesson.id
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

    equal_share = round(100 / len(topics), 2)
    for t in topics:
        t.weight = equal_share
        t.save()
    return


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def distribute_topic_weights_equally(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only modify topics for your own lessons.")

    topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)

    calculated_weight = 100 / len(topics)
    for t in topics:
        t.weight = calculated_weight
        t.save()
    return redirect('lesson:lesson_details', pk=lesson.id)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def create_subtopic(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only create subtopics for your own lessons.")

    if request.method == "POST":
        form = SubtopicForm(request.POST, lesson=lesson)

        if form.is_valid():
            subtopic = form.save(commit=False)
            subtopic.lesson = lesson
            parent = form.cleaned_data.get('parent')

            # Auto-assign order: next available order number within parent topic
            max_order = Topic.objects.filter(lesson=lesson, parent=parent).aggregate(
                max_order=models.Max('order')
            )['max_order'] or 0
            subtopic.order = max_order + 1
            subtopic.weight = 0
            subtopic.save()

            subtopic_weight_distribution(lesson)
        else:
            from django.contrib import messages
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error in {field}: {error}")

    return redirect('lesson:lesson_details', pk=pk)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def update_subtopic(request, pk):
    subtopic = get_object_or_404(Topic, pk=pk)
    lesson = subtopic.lesson

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only update subtopics for your own lessons.")

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
        from django.contrib import messages
        messages.warning(request, f"The total topic weight after editing is equal to {total_subtopic_weights}, but should be equal to 100.")

    return redirect('lesson:lesson_details')


def subtopic_weight_distribution(lesson):
    topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)

    for topic in topics:
        subtopics = list(Topic.objects.filter(parent=topic, lesson=lesson))
        
        if not subtopics:
            continue

        subtopic_count = len(subtopics)
        equal_share = round(100 / subtopic_count, 2)

        if subtopic_count > 1:
            calculated_sum = equal_share * subtopic_count
            if abs(calculated_sum - 100) > 0.01:
                for s in subtopics[:-1]:
                    s.weight = equal_share
                    s.save(update_fields=['weight'])
                last_subtopic = subtopics[-1]
                last_subtopic.weight = round(100 - (equal_share * (subtopic_count - 1)), 2)
                last_subtopic.save(update_fields=['weight'])
            else:
                for s in subtopics:
                    s.weight = equal_share
                    s.save(update_fields=['weight'])
        else:
            subtopics[0].weight = 100.0
            subtopics[0].save(update_fields=['weight'])


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def distribute_subtopic_weights_equally(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only modify subtopics for your own lessons.")

    subtopic_weight_distribution(lesson)
    return redirect('lesson:lesson_details', pk=lesson.id)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def grading(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)

    # Object-level permission: verify teacher owns this lesson's subject
    if not can_modify_lesson(request.user, lesson):
        return permission_denied_response("You can only grade lessons for your own subjects.")

    students = Student.objects.filter(
        enrollments__class_group=lesson.offering.class_group,
        enrollments__academic_year=lesson.offering.academic_year,
        enrollments__status='active'
    ).distinct()
    topics = Topic.objects.filter(lesson=lesson)
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


    # Comments merged/selecteed
    merged_comments = (
        MergedLessonComment.objects
        .filter(lesson=lesson, student__in=students)
        .select_related("student__user")
        .values("student__user_id", "comment_text")
    )
    merged_comment_map = {
        merged_comment["student__user_id"]: merged_comment["comment_text"] for merged_comment in merged_comments
    }

    selected_comments = (
        TopicGrade.objects
        .filter(topic__lesson=lesson, comment_selected=True)
        .select_related("student__user")
        .values("student__user_id", "comment").exclude(comment__isnull=True).exclude(comment="")
    )
    selected_comments_map = {
        selected_comment["student__user_id"]: selected_comment["comment"] for selected_comment in selected_comments
    }

    comment_modes = {}
    for student in students:
        if student.user.id in merged_comment_map:
            comment_modes[student.user.id] = "merged"
        elif student.user.id in selected_comments_map:
            comment_modes[student.user.id] = "selected"
        else:
            comment_modes[student.user.id] = None

    # comment templates
    comment_templates = {}
    for topic in topics:
        comment_templates[topic.id] = topic.comment_template

    student_grades = {}
    for student in students:
        student_grades[student.user.id] = round(lesson.calculate_student_grade(student), 1)




    context = {
        "lesson": lesson,
        "students": students,
        "topics": topics,
        "topic_grade_map": json.dumps(topic_grade_map, ensure_ascii=False),
        "student_grades": student_grades,
        "has_grades": has_grades,
        "merged_comment_map": merged_comment_map,  #json.dumps(merged_comment_map, ensure_ascii=False),
        "merged_comment_map_json": json.dumps(merged_comment_map, ensure_ascii=False),
        "selected_comments_map": selected_comments_map,
        "selected_comments_map_json": json.dumps(selected_comments_map, ensure_ascii=False),
        "comment_templates": json.dumps(comment_templates, ensure_ascii=False),
        "comment_modes": comment_modes,
    }
    return render(request, "lesson/grading.html", context)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def submit_all_topic_grades(request):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        lesson_id = request.POST.get('lesson_id')
        comment_mode = request.POST.get('comment_mode')

        try:
            student_id = int(student_id)
            lesson_id = int(lesson_id)
        except (ValueError, TypeError):
            return redirect('lesson:lessons')

        student = get_object_or_404(Student, user__id=student_id)
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        # Object-level permission: verify teacher can grade this student for this lesson
        if not can_grade_student(request.user, lesson, student):
            return permission_denied_response("You can only grade students in your own subjects.")

        toMerge = ""

        for topic in lesson.topics.filter(parent__isnull=True):
            subtopics = list(topic.subtopics.all())
            top_defaults = {
                'comment': request.POST.get(f'topic_{topic.id}_comment', '').strip(),
                'comment_selected': bool(request.POST.get(f'topic_{topic.id}_comment_selected', ''))
            }

            if comment_mode == "merged":
                toMerge += f"{topic.title}:"+ top_defaults['comment'] + '\n'


            for sub in subtopics:
                covered = request.POST.get(f'subtopic_{sub.id}_covered')
                grade_value = 100 if covered else 0

                sub_defaults = {'grade': grade_value,
                            'comment': request.POST.get(f'subtopic_{sub.id}_comment', '').strip(),
                            'comment_selected': False}

                if comment_mode == "merged":
                    toMerge += f"{topic.title} -- {sub.title}: " + sub_defaults['comment'] + '\n'

                TopicGrade.objects.update_or_create(
                    student=student,
                    topic=sub,
                    defaults=sub_defaults)


            if subtopics:
                topic_grade_value = topic.calculate_subtopics_grade(student)
            else:
                covered = request.POST.get(f'topic_{topic.id}_covered')
                topic_grade_value = 100 if covered else 0

            top_defaults['grade'] = topic_grade_value

            TopicGrade.objects.update_or_create(
                student=student,
                topic=topic,
                defaults=top_defaults
            )

        if comment_mode == "merged":
            TopicGrade.objects.filter(
                topic__lesson=lesson,
                student=student
            ).update(comment_selected=False)

            MergedLessonComment.objects.update_or_create(
                lesson=lesson,
                student=student,
                defaults={'comment_text': toMerge}
            )
        else:

            MergedLessonComment.objects.filter(
                lesson=lesson,
                student=student
            ).delete()

        return redirect('lesson:grading', pk=lesson.id)
    return redirect('lesson:lessons')


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


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def update_grade(request, pk=None):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        lesson_id = request.POST.get('lesson_id')

        student = get_object_or_404(Student, user__id=student_id)
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        # Object-level permission: verify teacher can grade this student for this lesson
        if not can_grade_student(request.user, lesson, student):
            return permission_denied_response("You can only update grades for students in your own subjects.")

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


@role_required('teacher', 'admin', 'supervisor')
def delete_grade(request, student_id, lesson_id):
    if request.method == 'POST':
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        student = get_object_or_404(Student, user__id=student_id)

        # Object-level permission: verify teacher can modify grades for this lesson
        if not can_grade_student(request.user, lesson, student):
            return permission_denied_response("You can only delete grades for students in your own subjects.")

        topic_grades = TopicGrade.objects.filter(student_id=student_id, topic__lesson=lesson)
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

