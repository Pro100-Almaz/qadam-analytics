#!/usr/bin/env python
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os
import sys
from sshtunnel import SSHTunnelForwarder
from dotenv import load_dotenv

load_dotenv()

def main():

    ssh_host = os.getenv('SSH_HOST')
    ssh_port = 22
    ssh_username = os.getenv('SSH_USERNAME')

    remote_db_host = os.getenv('REMOTE_DB_HOST')
    remote_db_port = int(os.getenv('REMOTE_DB_PORT'))

    local_bind_host = '127.0.0.1'
    local_bind_port = 0

    os.environ.setdefault('DB_NAME', os.getenv('DB_NAME'))
    os.environ.setdefault('DB_USER', os.getenv('DB_USER'))
    os.environ.setdefault('DB_PASSWORD', os.getenv('DB_PASSWORD'))

    with SSHTunnelForwarder(
        (ssh_host, ssh_port),
        ssh_username = ssh_username,
        remote_bind_address = (remote_db_host, remote_db_port),
        local_bind_address = (local_bind_host, local_bind_port)
    ) as tunnel:
        os.environ['DB_HOST'] = local_bind_host
        os.environ['DB_PORT'] = str(tunnel.local_bind_port)

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

        from django.core.management import execute_from_command_line
        execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()