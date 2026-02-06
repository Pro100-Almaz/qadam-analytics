from django.template.loader import render_to_string
from django.http import JsonResponse

def show_alert_modal(request, message):
    html_content = render_to_string(
        'components/alert_modal/modal_content.html',
        {'message': message},
        request=request
    )

    return JsonResponse({
        'status': 'show_modal',
        'html_content': html_content}
    )