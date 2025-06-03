import asyncio
import aiohttp
import os
import random
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import List, Dict, Any
from dotenv import load_dotenv
import logging
from urllib.parse import parse_qs, urlparse
from doctors import DOCTORS

# Load environment variables
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DoctolibWatcher:
    def __init__(self):
        # Import doctors from external file
        self.base_urls = DOCTORS
        
        # Discord webhook configuration
        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        if not self.discord_webhook_url:
            logger.warning("DISCORD_WEBHOOK_URL not set - notifications will be logged only")
        
        self.days_to_check = int(os.getenv('DAYS_TO_CHECK', 100))
        self.interval_between_checks = int(os.getenv('INTERVAL_BETWEEN_CHECKS', 300))
        
        # Initialize SQLite database
        self.db_path = 'sent_slots.db'
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database for tracking sent slots"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_identifier TEXT NOT NULL,
                slot_datetime TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(doctor_identifier, slot_datetime)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized")
    
    def _extract_url_identifiers(self, url: str) -> str:
        """Extract identifiers from URL to create a unique name"""
        try:
            parsed_url = urlparse(url)
            params = parse_qs(parsed_url.query)
            
            visit_motive_ids = params.get('visit_motive_ids', [''])[0]
            agenda_ids = params.get('agenda_ids', [''])[0]
            practice_ids = params.get('practice_ids', [''])[0]
            
            # Create a readable identifier
            identifier = f"VM{visit_motive_ids}_AG{agenda_ids}_PR{practice_ids}"
            return identifier
        except Exception as e:
            logger.warning(f"Could not extract identifiers from URL: {url}, error: {e}")
            return "Unknown"
    
    def _is_slot_already_sent(self, doctor_identifier: str, slot: str) -> bool:
        """Check if a slot has already been sent for a doctor"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT COUNT(*) FROM sent_slots WHERE doctor_identifier = ? AND slot_datetime = ?',
            (doctor_identifier, slot)
        )
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def _mark_slot_as_sent(self, doctor_identifier: str, slot: str):
        """Mark a slot as sent in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO sent_slots (doctor_identifier, slot_datetime) VALUES (?, ?)',
                (doctor_identifier, slot)
            )
            conn.commit()
            logger.debug(f"Marked slot as sent: {doctor_identifier} - {slot}")
        except sqlite3.IntegrityError:
            # Slot already exists, which is fine
            logger.debug(f"Slot already marked as sent: {doctor_identifier} - {slot}")
        finally:
            conn.close()
    
    def _cleanup_old_slots(self, days_old: int = 30):
        """Remove slots older than specified days to allow re-notification"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff_date = datetime.now() - timedelta(days=days_old)
        cursor.execute(
            'DELETE FROM sent_slots WHERE sent_at < ?',
            (cutoff_date.isoformat(),)
        )
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old slot records")
    
    def _generate_url_with_date(self, base_url: str, start_date: datetime) -> str:
        """Generate URL with specific start date"""
        date_str = start_date.strftime('%Y-%m-%d')
        # Replace the start_date parameter in the URL
        if 'start_date=' in base_url:
            # Find and replace existing start_date
            parts = base_url.split('&')
            new_parts = []
            for part in parts:
                if part.startswith('start_date='):
                    new_parts.append(f'start_date={date_str}')
                else:
                    new_parts.append(part)
            return '&'.join(new_parts)
        else:
            # Add start_date parameter
            separator = '&' if '?' in base_url else '?'
            return f"{base_url}{separator}start_date={date_str}"
    
    def _generate_urls_for_period(self, base_url: str) -> List[str]:
        """Generate URLs for the specified period (chunked by 15-day periods)"""
        urls = []
        current_date = datetime.now().date()
        
        # Calculate how many 15-day chunks we need
        chunks_needed = (self.days_to_check + 14) // 15  # Round up
        
        for i in range(chunks_needed):
            start_date = current_date + timedelta(days=i * 15)
            url = self._generate_url_with_date(base_url, start_date)
            urls.append(url)
            
        return urls
    
    async def _fetch_availabilities(self, session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
        """Fetch availability data from a single URL"""
        try:
            # Random sleep between 2 and 5 seconds to avoid bot detection
            sleep_time = random.uniform(2, 5)
            await asyncio.sleep(sleep_time)
            
            # Set browser-like headers
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Priority': 'u=0, i',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:138.0) Gecko/20100101 Firefox/138.0'
            }
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Successfully fetched data from {url}")
                    return data
                else:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return {}
    
    def _extract_available_slots(self, data: Dict[str, Any]) -> List[str]:
        """Extract all available slots from the API response"""
        slots = []
        if 'availabilities' in data:
            for availability in data['availabilities']:
                if availability.get('slots'):
                    slots.extend(availability['slots'])
        return slots
    
    async def _send_discord_notification(self, session: aiohttp.ClientSession, message: str) -> bool:
        """Send Discord notification via webhook and return success status"""
        if not self.discord_webhook_url:
            logger.info(f"No Discord webhook configured. Message would be: {message}")
            return True  # Consider it successful if no webhook is configured
        
        try:
            # Create Discord embed for better formatting
            embed = {
                "title": "🏥 Doctolib Slots Available!",
                "description": message,
                "color": 0x00ff00,  # Green color
                "timestamp": datetime.now(UTC).isoformat(),
                "footer": {
                    "text": "Doctolib Watcher"
                }
            }
            
            payload = {
                "embeds": [embed]
            }
            
            async with session.post(self.discord_webhook_url, json=payload) as response:
                if response.status in [200, 204]:
                    logger.info("Discord notification sent successfully")
                    return True
                else:
                    logger.error(f"Failed to send Discord notification: HTTP {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {str(e)}")
            return False
    
    def _format_slot_time(self, slot: str) -> str:
        """Format slot time for notification"""
        try:
            dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M')
        except Exception as e:
            logger.error(f"Error formatting slot time {slot}: {str(e)}")
            return slot
    
    async def _process_doctor(self, session: aiohttp.ClientSession, doctor: Dict[str, str]):
        """Process all URLs for a single doctor"""
        base_url = doctor["url"]
        
        # Use provided name or extract from URL
        doctor_identifier = doctor.get("name")
        if not doctor_identifier:
            doctor_identifier = self._extract_url_identifiers(base_url)
        
        urls = self._generate_urls_for_period(base_url)
        new_slots = []
        
        # Fetch all URLs for this doctor concurrently
        tasks = [self._fetch_availabilities(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        # Process all results
        for data in results:
            if data:
                slots = self._extract_available_slots(data)
                for slot in slots:
                    # Check if this slot has already been sent
                    if not self._is_slot_already_sent(doctor_identifier, slot):
                        new_slots.append(slot)
        
        # Send Discord notification if new slots found
        if new_slots:
            formatted_slots = [self._format_slot_time(slot) for slot in new_slots]
            message = f"**New slots for {doctor_identifier}:**\n" + "\n".join(f"• {slot}" for slot in formatted_slots[:10])
            if len(new_slots) > 10:
                message += f"\n... and {len(new_slots) - 10} more slots"
            
            # Try to send Discord notification first
            notification_sent = await self._send_discord_notification(session, message)
            
            # Only mark slots as sent if notification was successful
            if notification_sent:
                for slot in new_slots:
                    self._mark_slot_as_sent(doctor_identifier, slot)
                logger.info(f"Found {len(new_slots)} new slots for {doctor_identifier}")
            else:
                logger.warning(f"Discord notification failed for {doctor_identifier}, not marking slots as sent")
        else:
            # Only log, don't send notification for no new slots
            logger.info(f"No new slots found for {doctor_identifier}")
    
    async def check_availabilities(self):
        """Check availabilities for all doctors"""
        if not self.base_urls:
            logger.warning("No doctors configured")
            return
        
        logger.info(f"Checking availabilities for {len(self.base_urls)} doctors")
        
        # Cleanup old slots periodically (every check)
        self._cleanup_old_slots(days_old=30)
        
        # Create session with default headers
        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Process all doctors concurrently
            tasks = [self._process_doctor(session, doctor) for doctor in self.base_urls]
            await asyncio.gather(*tasks)
    
    async def run_scheduler(self):
        """Run the scheduler that checks every interval"""
        logger.info("Starting Doctolib watcher...")
        
        while True:
            try:
                await self.check_availabilities()
                logger.info(f"Waiting {self.interval_between_checks} seconds before next check...")
                await asyncio.sleep(self.interval_between_checks)
            except KeyboardInterrupt:
                logger.info("Scheduler stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in scheduler: {str(e)}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying

async def main():
    watcher = DoctolibWatcher()
    await watcher.run_scheduler()

if __name__ == "__main__":
    asyncio.run(main())