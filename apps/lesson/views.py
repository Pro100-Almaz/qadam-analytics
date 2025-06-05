from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse

from .forms import LessonForm
from .models import Lesson, StudentGrade, Comment
from apps.authentication.models import CustomUser
from apps.home.models import Subject, ClassRoom


def calculate_grade(points, maximum_points):
    """
    Calculate grade based on points and maximum points
    Grade scale:
    5: 90-100% of maximum points
    4: 75-89% of maximum points
    3: 60-74% of maximum points
    2: 40-59% of maximum points
    1: 0-39% of maximum points
    """
    if not points or not maximum_points:
        return None
    
    percentage = (points / maximum_points) * 100
    
    if percentage >= 90:
        return 5
    elif percentage >= 75:
        return 4
    elif percentage >= 60:
        return 3
    elif percentage >= 40:
        return 2
    else:
        return 1


def get_comment_for_points(points, lesson):
    """
    Get appropriate comment template based on points
    """
    if not points or not lesson:
        return ''
    
    try:
        comment = Comment.objects.filter(
            lesson=lesson,
            from_points__lte=points,
            to_points__gte=points
        ).first()
        return comment.comment_text if comment else ''
    except Comment.DoesNotExist:
        return ''


@login_required(login_url="/login/")
def lessons_list(request):
    classroom_filter = request.GET.get('classroom')
    subject_filter = request.GET.get('subject')
    lessons = Lesson.objects.all()
    classrooms = ClassRoom.objects.all()
    subjects = [] if classroom_filter == "all" or classroom_filter is None else Subject.objects.filter(classroom__name=classroom_filter)
    
    number_of_students = {}

    if classroom_filter and classroom_filter != "all":
        lessons = lessons.filter(subject__classroom__name=classroom_filter)

    if subject_filter and subject_filter != "all":
        lessons = lessons.filter(subject__name=subject_filter)

    for lesson in lessons:
        number_of_students[lesson.title] = CustomUser.objects.filter(classroom=lesson.subject.classroom).count()

    page = request.GET.get('page')
    paginator = Paginator(lessons, 5)
    page_obj = paginator.get_page(page)

    context = {'lessons': lessons,
               "number_of_students": number_of_students,
               "classrooms": classrooms,
               "classroom_filter": classroom_filter,
               "subject_filter": subject_filter,
               "subjects": subjects,
               "page_obj": page_obj}
    if request.method == 'POST':
        pass

    return render(request, 'lesson/lessons.html', context)


@login_required(login_url="/login/")
def lesson_details_json(request, pk):
    # subject_id = request.GET.get('subject')
    student_id = request.GET.get('student_id')

    try:
        # Get the student and subject
        student = get_object_or_404(CustomUser, id=student_id, role='student')
        subject = get_object_or_404(Subject, pk=pk)

        # Get all lessons for the subject
        lessons = Lesson.objects.filter(subject=subject).order_by('-created_at')
        
        # Get grades for each lesson
        lessons_data = []
        for lesson in lessons:
            grade = StudentGrade.objects.filter(
                lesson=lesson,
                student=student
            ).first()
            
            lessons_data.append({
                'id': lesson.id,
                'title': lesson.title,
                'date': lesson.created_at.strftime('%Y-%m-%d'),
                'maximum_points': lesson.maximum_points,
                'points': grade.points if grade else None,
                'grade': grade.grade if grade else None,
                'comment': grade.comment if grade else None,
            })
        return JsonResponse({

            'success': True,
            'lessons': lessons_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


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
def lesson_details(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    student_grades = StudentGrade.objects.filter(lesson=lesson)
    comments = Comment.objects.filter(lesson=lesson)
    
    context = {
        'lesson': lesson,
        'student_grades': student_grades,
        'comments': comments,
    }
    return render(request, 'lesson/lesson_details.html', context)


@login_required(login_url="/login/")
def grading(request):
    if request.method in ['POST', 'PUT']:
        lesson_id = request.POST.get('lesson_id')
        student_id = request.POST.get('student_id')
        grade_id = request.POST.get('grade_id')
        action = request.POST.get('action')
        
        if not Lesson.objects.filter(id=lesson_id).exists():
            return render(request, 'home/page-404.html')
        
        lesson = Lesson.objects.get(id=lesson_id)

        if action == 'update':
            if not grade_id:
                messages.error(request, "Grade ID is required for update!")
                return redirect('lesson_details', pk=lesson_id)

            try:
                grade = StudentGrade.objects.get(id=grade_id)
                points = request.POST.get('points')
                grade_value = request.POST.get('grade')

                if points and points.strip():
                    try:
                        points = int(points)
                        if points < 0 or points > lesson.maximum_points:
                            messages.error(request, f"Points must be between 0 and {lesson.maximum_points}!")
                            return redirect('lesson_details', pk=lesson_id)
                        grade.points = points
                        grade.grade = calculate_grade(points, lesson.maximum_points)
                        grade.comment = get_comment_for_points(points, lesson)
                    except ValueError:
                        messages.error(request, "Points must be a valid number!")
                        return redirect('lesson_details', pk=lesson_id)
                
                if grade_value and grade_value.strip():
                    try:
                        grade_value = int(grade_value)
                        if grade_value not in [1, 2, 3, 4, 5]:
                            messages.error(request, "Grade must be between 1 and 5!")
                            return redirect('lesson_details', pk=lesson_id)
                        grade.grade = grade_value
                    except ValueError:
                        messages.error(request, "Grade must be a valid number!")
                        return redirect('lesson_details', pk=lesson_id)

                grade.save()
                messages.success(request, "Grade updated successfully!")
                return redirect('lesson:lesson_details', pk=lesson_id)

            except StudentGrade.DoesNotExist:
                messages.error(request, "Grade not found!")
                return redirect('lesson_details', pk=lesson_id)

        if not CustomUser.objects.filter(id=student_id, role='student').exists():
            return render(request, 'home/page-404.html')

        points = request.POST.get(f'points_{student_id}')

        try:
            existing_grade = StudentGrade.objects.get(lesson_id=lesson_id, student_id=student_id)
            if not points or not points.strip():
                points = existing_grade.points
        except StudentGrade.DoesNotExist:
            if not points or not points.strip():
                messages.error(request, "Points cannot be empty for new grades!")
                return redirect('lesson_details', pk=lesson_id)

        try:
            points = int(points)
            if points < 0 or points > lesson.maximum_points:
                messages.error(request, f"Points must be between 0 and {lesson.maximum_points}!")
                return redirect('lesson_details', pk=lesson_id)
        except ValueError:
            messages.error(request, "Points must be a valid number!")
            return redirect('lesson_details', pk=lesson_id)

        grade_value = calculate_grade(points, lesson.maximum_points)
        comment = get_comment_for_points(points, lesson)

        grade, created = StudentGrade.objects.update_or_create(
            lesson_id=lesson_id,
            student_id=student_id,
            defaults={
                'grade': grade_value,
                'points': points,
                'comment': comment
            }
        )

        messages.success(request, "Grade updated successfully!")
        return redirect('lesson:lesson_details', pk=lesson_id)

    # GET request handling
    lesson_id = request.GET.get('lesson_id')
    if not lesson_id:
        return render(request, 'home/page-404.html')

    lesson = get_object_or_404(Lesson, id=lesson_id)
    students = CustomUser.objects.filter(role='student', classroom=lesson.subject.classroom)
    
    existing_grades = StudentGrade.objects.filter(lesson=lesson)
    student_grades = {}
    for grade in existing_grades:
        student_grades[grade.student.id] = {
            'grade': grade.grade,
            'points': grade.points,
            'comment': grade.comment
        }

    context = {
        'lesson': lesson,
        'students': students,
        'student_grades': student_grades
    }
    return render(request, 'lesson/grading.html', context)


@login_required(login_url="/login/")
def comment_template_create(request):
    if request.method == 'POST':
        from_points = request.POST.get('from_points')
        to_points = request.POST.get('to_points')
        comment_text = request.POST.get('comment_text')
        lesson_id = request.POST.get('lesson_id')

        try:
            from_points = int(from_points)
            to_points = int(to_points)
            
            if from_points > to_points:
                messages.error(request, "Начальное значение баллов не может быть больше конечного!")
                return redirect(request.META.get('HTTP_REFERER', '/'))

            lesson = get_object_or_404(Lesson, id=lesson_id) if lesson_id else None
            comment = Comment.objects.create(
                lesson=lesson,
                from_points=from_points,
                to_points=to_points,
                comment_text=comment_text
            )
            
            messages.success(request, "Шаблон комментария успешно создан!")
            return redirect(request.META.get('HTTP_REFERER', '/'))

        except ValueError:
            messages.error(request, "Пожалуйста, введите корректные числовые значения для баллов!")
            return redirect(request.META.get('HTTP_REFERER', '/'))
        except Exception as e:
            messages.error(request, f"Произошла ошибка при создании шаблона: {str(e)}")
            return redirect(request.META.get('HTTP_REFERER', '/'))

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required(login_url="/login/")
def comment_template_update(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    
    if request.method == 'POST':
        from_points = request.POST.get('from_points')
        to_points = request.POST.get('to_points')
        comment_text = request.POST.get('comment_text')
        
        try:
            from_points = int(from_points)
            to_points = int(to_points)
            
            if from_points > to_points:
                messages.error(request, "Начальное значение баллов не может быть больше конечного!")
                return redirect(request.META.get('HTTP_REFERER', '/'))
            
            comment.from_points = from_points
            comment.to_points = to_points
            comment.comment_text = comment_text
            comment.save()
            
            messages.success(request, "Шаблон комментария успешно обновлен!")
            return redirect(request.META.get('HTTP_REFERER', '/'))
            
        except ValueError:
            messages.error(request, "Пожалуйста, введите корректные числовые значения для баллов!")
            return redirect(request.META.get('HTTP_REFERER', '/'))
        except Exception as e:
            messages.error(request, f"Произошла ошибка при обновлении шаблона: {str(e)}")
            return redirect(request.META.get('HTTP_REFERER', '/'))
    
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required(login_url="/login/")
def comment_template_delete(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    
    try:
        comment.delete()
        messages.success(request, "Шаблон комментария успешно удален!")
    except Exception as e:
        messages.error(request, f"Произошла ошибка при удалении шаблона: {str(e)}")
    
    return redirect(request.META.get('HTTP_REFERER', '/'))
