"""
Medication Alarm Background Worker
Checks database every minute and sends web push notifications for medication times
Works with anonymous 17-digit code system
"""

import os
import time
import logging
from datetime import datetime, timedelta
from pywebpush import webpush, WebPushException
import json
from db_manager import DatabaseManager
from encryption import decrypt_data

print(" ")

if __name__ == '__main__':
    worker = AlarmWorker()
    worker.run()
