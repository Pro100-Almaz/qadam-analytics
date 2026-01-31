#psychological state email sending signal
# @receiver(pre_save, sender=PsychologicalState)
# def psycho_state_pre_save(sender, instance, **kwargs):
#     added_by_user = instance.added_by
#     target_student = instance.student
#     student_custom_user = target_student.user
#
#     try:
#         parent = Parent.objects.get(student__user=student_custom_user)
#     except Parent.DoesNotExist:
#         parent = None
#
#
#     subject = "Уведомление об обновлении отчета о Психическом Состоянии Студента"
#     html_message = render_to_string("email/psychological_state_student_email.html",
#                                    {"student": target_student, "adder": added_by_user})
#     plain_message = strip_tags(html_message)
#     from_mail = settings.DEFAULT_FROM_EMAIL
#     to_mail = [student_custom_user.email]
#
#     send_mail(
#         subject=subject,
#         message=plain_message,
#         from_email=from_mail,
#         recipient_list=to_mail,
#         html_message=html_message
#     )
#
#     if parent:
#         parent_user = parent.user
#
#         subject_parent = "Psychological State Update"
#         html_message_parent = render_to_string("email/psychological_state_parent_email.html",
#                                                {"parent": parent_user, "adder": added_by_user})
#         plain_message_parent = strip_tags(html_message_parent)
#         from_mail_parent = settings.DEFAULT_FROM_EMAIL
#         to_mail_parent = [parent_user.email]
#
#         send_mail(
#             subject=subject_parent,
#             message=plain_message_parent,
#             from_email=from_mail_parent,
#             recipient_list=to_mail_parent,
#             html_message=html_message_parent
#         )
#
#         from apps.notification.models import Notification, PsychologicalNotify
#         notification = Notification.objects.create(user=student_custom_user, action='psychological_state')
#         PsychologicalNotify.objects.create(notification=notification, parent=parent, psychologist=added_by_user)
#
#     else:
#         from apps.notification.models import Notification, PsychologicalNotify
#         notification = Notification.objects.create(user=target_student, action='psychological_state')
#         PsychologicalNotify.objects.create(notification=notification, psychologist=added_by_user)
#