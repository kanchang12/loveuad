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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AlarmWorker:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.vapid_private_key = os.environ.get('VAPID_PRIVATE_KEY')
        self.vapid_public_key = os.environ.get('VAPID_PUBLIC_KEY')
        self.vapid_claims = {
            "sub": "mailto:support@loveuad.com"
        }
        
    def check_and_send_alarms(self):
        """Check for medications due now and send push notifications"""
        try:
            current_time = datetime.now().strftime('%H:%M')
            logger.info(f"Checking alarms for {current_time}")
            
            with self.db_manager.get_connection() as conn:
                cur = conn.cursor()
                
                # Get all active alarms for this time
                cur.execute("""
                    SELECT DISTINCT m.code_hash, m.medication_name, m.time
                    FROM medication_reminders m
                    WHERE m.time::text LIKE %s || '%%' 
                    AND m.active = true
                """, (current_time,))
                
                due_medications = cur.fetchall()
                
                if not due_medications:
                    logger.info(f"No medications due at {current_time}")
                    return
                
                logger.info(f"Found {len(due_medications)} medication(s) due")
                
                # Group by code_hash
                alarms_by_user = {}
                for med in due_medications:
                    code_hash = med['code_hash']
                    if code_hash not in alarms_by_user:
                        alarms_by_user[code_hash] = []
                    alarms_by_user[code_hash].append({
                        'name': med['medication_name'],
                        'time': str(med['time'])
                    })
                
                # Send push notification to each user
                for code_hash, medications in alarms_by_user.items():
                    self.send_push_notification(code_hash, medications)
                    
        except Exception as e:
            logger.error(f"Alarm check error: {e}", exc_info=True)
    
    def send_push_notification(self, code_hash, medications):
        """Send web push notification to user"""
        try:
            with self.db_manager.get_connection() as conn:
                cur = conn.cursor()
                
                # Get push subscription for this user
                cur.execute("""
                    SELECT subscription_data FROM push_subscriptions 
                    WHERE code_hash = %s AND active = true
                """, (code_hash,))
                
                subscriptions = cur.fetchall()
                
                if not subscriptions:
                    logger.warning(f"No push subscriptions for {code_hash[:8]}...")
                    return
                
                # Create notification payload
                med_names = ", ".join([m['name'] for m in medications])
                payload = json.dumps({
                    "title": "🔔 MEDICATION TIME",
                    "body": f"Time to take: {med_names}",
                    "icon": "/static/icon-192.png",
                    "badge": "/static/badge-72.png",
                    "tag": "medication-alarm",
                    "requireInteraction": True,
                    "vibrate": [200, 100, 200, 100, 200, 100, 200],
                    "data": {
                        "url": "/alarm",
                        "medications": medications
                    }
                })
                
                # Send to all subscriptions for this user
                for sub_record in subscriptions:
                    try:
                        subscription_info = json.loads(sub_record['subscription_data'])
                        
                        webpush(
                            subscription_info=subscription_info,
                            data=payload,
                            vapid_private_key=self.vapid_private_key,
                            vapid_claims=self.vapid_claims
                        )
                        
                        logger.info(f"✓ Push sent to {code_hash[:8]}... for {med_names}")
                        
                    except WebPushException as e:
                        logger.error(f"Push failed: {e}")
                        if e.response and e.response.status_code == 410:
                            # Subscription expired - mark as inactive
                            cur.execute("""
                                UPDATE push_subscriptions 
                                SET active = false 
                                WHERE subscription_data = %s
                            """, (json.dumps(subscription_info),))
                            conn.commit()
                            
        except Exception as e:
            logger.error(f"Push notification error: {e}", exc_info=True)
    
    def run(self):
        """Main loop - check every minute"""
        logger.info("="*60)
        logger.info("Medication Alarm Worker Started")
        logger.info("Checking for due medications every 60 seconds")
        logger.info("="*60)
        
        while True:
            try:
                self.check_and_send_alarms()
                time.sleep(60)  # Check every minute
            except KeyboardInterrupt:
                logger.info("Alarm worker stopped")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                time.sleep(60)

if __name__ == '__main__':
    worker = AlarmWorker()
    worker.run()
