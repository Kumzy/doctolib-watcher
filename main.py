import asyncio
import aiohttp
import os
import random
from datetime import datetime, timedelta
from typing import Set, List, Dict, Any
from twilio.rest import Client
from dotenv import load_dotenv
import logging
from doctors import DOCTORS

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DoctolibWatcher:
    def __init__(self):
        # Import doctors from external file
        self.base_urls = DOCTORS
        
        self.twilio_client = Client(
            username=os.getenv('TWILIO_ACCOUNT_SID'),
            password=os.getenv('TWILIO_AUTH_TOKEN')
        )
        self.twilio_from = os.getenv('TWILIO_FROM_NUMBER')
        self.twilio_to = os.getenv('TWILIO_TO_NUMBER')
        self.sent_slots: Set[str] = set()  # Track sent slots to avoid duplicates
        self.days_to_check = int(os.getenv('DAYS_TO_CHECK', 100))
        self.interval_between_checks = int(os.getenv('INTERVAL_BETWEEN_CHECKS', 300))  # Default to 5 minutes
    
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
    
    def _send_sms(self, message: str):
        """Send SMS via Twilio"""
        try:
            message = self.twilio_client.messages.create(
                body=message,
                from_=self.twilio_from,
                to=self.twilio_to
            )
            logger.info(f"SMS sent successfully: {message.sid}")
        except Exception as e:
            logger.error(f"Failed to send SMS: {str(e)}")
    
    def _format_slot_time(self, slot: str) -> str:
        """Format slot time for SMS"""
        try:
            dt = datetime.fromisoformat(slot.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M')
        except:
            return slot
    
    async def _process_doctor(self, session: aiohttp.ClientSession, doctor: Dict[str, str]):
        """Process all URLs for a single doctor"""
        doctor_name = doctor["name"]
        base_url = doctor["url"]
        
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
                    # Use doctor name + slot to create unique identifier
                    slot_id = f"{doctor_name}:{slot}"
                    if slot_id not in self.sent_slots:
                        new_slots.append(slot)
                        self.sent_slots.add(slot_id)
        
        # Send SMS if new slots found
        if new_slots:
            formatted_slots = [self._format_slot_time(slot) for slot in new_slots]
            message = f"New slots for {doctor_name}:\n" + "\n".join(formatted_slots[:10])  # Limit to 10 slots
            if len(new_slots) > 10:
                message += f"\n... and {len(new_slots) - 10} more slots"
            
            self._send_sms(message)
            logger.info(f"Found {len(new_slots)} new slots for {doctor_name}")
        else:
            message="nO NEW SLOTS FOUND"
            self._send_sms(message)
            logger.info(f"No new slots found for {doctor_name}")
    
    async def check_availabilities(self):
        """Check availabilities for all doctors"""
        if not self.base_urls:
            logger.warning("No doctors configured")
            return
        
        logger.info(f"Checking availabilities for {len(self.base_urls)} doctors")
        
        # Create session with default headers
        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Process all doctors concurrently
            tasks = [self._process_doctor(session, doctor) for doctor in self.base_urls]
            await asyncio.gather(*tasks)
    
    async def run_scheduler(self):
        """Run the scheduler that checks every 5 minutes"""
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