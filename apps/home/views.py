from django import template
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.template import loader
from django.urls import reverse, reverse_lazy
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Avg

from apps.home.forms import LessonForm, LessonGroupForm
from apps.home.models import Lesson, StudentGrade, ClassRoom, Subject, Comment
from apps.authentication.models import CustomUser


@login_required(login_url="/login/")
def index(request):
    context = {'segment': 'index'}

    return render(request, 'home/index.html', context)

@login_required(login_url="/login/")
def pages(request):
    context = {}
    try:

        load_template = request.path.split('/')[-1]

        if load_template == 'admin':
            return HttpResponseRedirect(reverse('admin:index'))

        # elif load_template == 'pages':

        context['segment'] = load_template


        return render(request, 'home/' + load_template, context)

    except template.TemplateDoesNotExist:

        html_template = loader.get_template('home/page-404.html')
        return render(request, 'home/page-404.html', context)

    except:
        html_template = loader.get_template('home/page-500.html')
        return render(request, 'home/page-500.html', context)


def lesson_group_create(request):
    if request.method == 'POST':
        form = LessonGroupForm(request.POST)
        if form.is_valid():
            form.save()
    return redirect(request.META.get('HTTP_REFERER','/'))


@login_required(login_url="/login/")
def lessons_list(request):
    lessons = Lesson.objects.all()
    number_of_students = {}
    for lesson in lessons:
        number_of_students[lesson.title] = CustomUser.objects.filter(classroom=lesson.subject.classroom).count()
    context = {'lessons': lessons, "number_of_students": number_of_students}

    if request.method == 'POST':
        pass

    return render(request, 'home/lessons.html', context)


@login_required(login_url="/login/")
def teachers_list(request):
    teachers = CustomUser.objects.filter(role='teacher')
    context = {'teachers': teachers}

    if request.method == 'POST':
        pass

    return render(request, 'home/teachers.html', context)

  
@login_required(login_url="/login/")
def students_list(request):
    students = CustomUser.objects.filter(role='student')
    classrooms = ClassRoom.objects.all()
    context = {'students': students, 'classrooms': classrooms}

    if request.method == 'POST':
        pass

    return render(request, 'home/students.html', context)

  
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
                comment = request.POST.get('comment')
                grade_value = request.POST.get('grade')

                if points and points.strip():
                    try:
                        points = int(points)
                        if points < 0 or points > lesson.maximum_points:
                            messages.error(request, f"Points must be between 0 and {lesson.maximum_points}!")
                            return redirect('lesson_details', pk=lesson_id)
                        grade.points = points
                        grade.grade = calculate_grade(points, lesson.maximum_points)
                    except ValueError:
                        messages.error(request, "Points must be a valid number!")
                        return redirect('lesson_details', pk=lesson_id)
                
                if comment is not None:
                    grade.comment = comment
                
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
                return redirect('lesson_details', pk=lesson_id)

            except StudentGrade.DoesNotExist:
                messages.error(request, "Grade not found!")
                return redirect('lesson_details', pk=lesson_id)

        if not CustomUser.objects.filter(id=student_id, role='student').exists():
            return render(request, 'home/page-404.html')

        points = request.POST.get(f'points_{student_id}')
        comment = request.POST.get(f'comment_{student_id}')

        try:
            existing_grade = StudentGrade.objects.get(lesson_id=lesson_id, student_id=student_id)
            if not points or not points.strip():
                points = existing_grade.points
            if not comment or not comment.strip():
                comment = existing_grade.comment
        except StudentGrade.DoesNotExist:
            if not points or not points.strip():
                messages.error(request, "Points cannot be empty for new grades!")
                return redirect('lesson_details', pk=lesson_id)
            if not comment:
                comment = ''

        try:
            points = int(points)
            if points < 0 or points > lesson.maximum_points:
                messages.error(request, f"Points must be between 0 and {lesson.maximum_points}!")
                return redirect('lesson_details', pk=lesson_id)
        except ValueError:
            messages.error(request, "Points must be a valid number!")
            return redirect('lesson_details', pk=lesson_id)

        grade_value = calculate_grade(points, lesson.maximum_points)

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
        return redirect('lesson_details', pk=lesson_id)

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
    return render(request, 'home/grading.html', context)


@login_required(login_url="/login/")
def lesson_create(request):
    if request.method == "POST":
        form = LessonForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "👩‍🏫 Lesson created successfully!")
            return redirect("lessons")
    else:
        form = LessonForm()

    return render(request, "home/new_lesson.html", {"form": form})


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
    return render(request, 'home/lesson_details.html', context)


@login_required(login_url="/login/")
def student_details(request, pk):
    student = get_object_or_404(CustomUser, pk=pk, role='student')
    
    # Get all subjects the student is taking through their classroom
    subjects = Subject.objects.filter(classroom=student.classroom)
    
    # Get all grades for this student
    grades = StudentGrade.objects.filter(student=student)
    
    # Calculate average grades per subject
    subject_averages = {}
    for subject in subjects:
        subject_grades = grades.filter(lesson__subject=subject)
        if subject_grades.exists():
            avg_grade = subject_grades.aggregate(Avg('grade'))['grade__avg']
            avg_points = subject_grades.aggregate(Avg('points'))['points__avg']
            subject_averages[subject] = {
                'average_grade': round(avg_grade, 2) if avg_grade else 0,
                'average_points': round(avg_points, 2) if avg_points else 0,
                'total_lessons': subject_grades.count(),
                'grades': subject_grades
            }
    
    # Get grades by quarter for chart
    quarter_grades = {}
    for quarter in range(1, 5):
        quarter_grades[quarter] = grades.filter(lesson__quarter=quarter).aggregate(
            Avg('grade'))['grade__avg'] or 0
    
    context = {
        'student': student,
        'subjects': subjects,
        'subject_averages': subject_averages,
        'quarter_grades': quarter_grades,
        'total_subjects': subjects.count(),
        'total_lessons': grades.count(),
    }
    
    return render(request, 'home/student_details.html', context)

@login_required(login_url="/login/")
def comment_template_create(request):
    if request.method == 'POST':
        from_points = request.POST.get('from_points')
        to_points = request.POST.get('to_points')
        comment_text = request.POST.get('comment_text')
        lesson_id = request.POST.get('lesson_id')
        print("Step 1")

        try:
            from_points = int(from_points)
            to_points = int(to_points)

            print("Step 2")
            
            if from_points > to_points:
                messages.error(request, "Начальное значение баллов не может быть больше конечного!")
                return redirect(request.META.get('HTTP_REFERER', '/'))

            print("Step 3")

            lesson = get_object_or_404(Lesson, id=lesson_id) if lesson_id else None
            print("Step 4")
            comment = Comment.objects.create(
                lesson=lesson,
                from_points=from_points,
                to_points=to_points,
                comment_text=comment_text
            )

            print("Step 5")
            
            messages.success(request, "Шаблон комментария успешно создан!")
            return redirect(request.META.get('HTTP_REFERER', '/'))

        except ValueError:
            print("Value error exception")
            messages.error(request, "Пожалуйста, введите корректные числовые значения для баллов!")
            return redirect(request.META.get('HTTP_REFERER', '/'))
        except Exception as e:
            print(str(e))
            messages.error(request, f"Произошла ошибка при создании шаблона: {str(e)}")
            return redirect(request.META.get('HTTP_REFERER', '/'))

    return redirect(request.META.get('HTTP_REFERER', '/'))

@login_required(login_url="/login/")
def comment_template_update(request, comment_id):
    if request.method == 'POST':
        comment = get_object_or_404(Comment, id=comment_id)
        from_points = request.POST.get('from_points')
        to_points = request.POST.get('to_points')
        comment_text = request.POST.get('comment_text')

        try:
            from_points = int(from_points)
            to_points = int(to_points)
            
            if from_points > to_points:
                messages.error(request, "Начальное значение баллов не может быть больше конечного!")
                return redirect(request.META.get('HTTP_REFERER', '/'))

            if from_points < 0 or to_points > 100:
                messages.error(request, "Баллы должны быть в диапазоне от 0 до 100!")
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
    if request.method == 'POST':
        comment = get_object_or_404(Comment, id=comment_id)
        try:
            comment.delete()
            messages.success(request, "Шаблон комментария успешно удален!")
        except Exception as e:
            messages.error(request, f"Произошла ошибка при удалении шаблона: {str(e)}")
    
    return redirect(request.META.get('HTTP_REFERER', '/'))
