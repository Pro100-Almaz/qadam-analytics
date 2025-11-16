
from django.db import transaction
from apps.authentication.models import Supervisor

import logging

logging.basicConfig(level=logging.DEBUG, filename="../script_logging.log", filemode="w",
                    format='%(asctime)s - %(levelname)s - %(message)s')


def process_supervisor(sheet_name, row, idx, admin_id, user):
    try:
        with transaction.atomic():
            Supervisor.objects.update_or_create(user=user)

    except Exception as e:
        msg = f"---->>>Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
        logging.error(msg)
