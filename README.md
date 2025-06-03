# Doctolib Watcher

A Python script that monitors Doctolib for available appointments and sends notifications via Discord webhooks. The script checks for new appointment slots at regular intervals and only sends notifications for slots that haven't been seen before, using SQLite to track notification history.

## Features

- 🔍 **Monitors multiple doctors/agendas** simultaneously
- 📅 **Configurable date range** for appointment checking
- 🚫 **No duplicate notifications** - uses SQLite to track sent notifications
- 🤖 **Anti-bot detection** with realistic browser headers and random delays
- 💬 **Discord notifications** with rich embeds
- 🧹 **Automatic cleanup** of old notification records
- ⚙️ **Easy configuration** with separate files for doctors and settings

## Setup

### 1. Install Dependencies

Make sure you have [uv](https://docs.astral.sh/uv/) installed, then run:

```bash
uv sync
```


### 2. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Discord webhook URL (required)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN

# Number of days ahead to check for appointments (default: 100)
DAYS_TO_CHECK=100

# Interval between checks in seconds (default: 300 = 5 minutes)
INTERVAL_BETWEEN_CHECKS=300
```

#### Setting up Discord Webhook:

1. Go to your Discord server
2. Navigate to **Server Settings** → **Integrations** → **Webhooks**
3. Click **"New Webhook"**
4. Choose the channel where you want notifications
5. Copy the webhook URL and paste it in your `.env` file

### 3. Configure Doctors

Edit the `doctors.py` file to add the doctors/appointments you want to monitor:

```python
DOCTORS = [
    {
        "name": "Dr. Smith",  # Optional: Custom name for notifications
        "url": "https://partners.doctolib.fr/availabilities.json?visit_motive_ids=123456&agenda_ids=789012&practice_ids=345678&telehealth=false&start_date=2025-06-02&limit=15"
    },
    {
        # No name provided - will auto-generate from URL parameters
        "url": "https://partners.doctolib.fr/availabilities.json?visit_motive_ids=654321&agenda_ids=210987&practice_ids=876543&telehealth=false&start_date=2025-06-02&limit=15"
    },
]
```

#### How to get Doctolib URLs:

1. **Go to the doctor's page** on Doctolib
2. **Select your appointment type** and preferences
3. **Open browser developer tools** (F12)
4. **Go to Network tab**, filter on ``XHR`` and look for requests to `availabilities.json`
5. **Copy the full URL** from the network request
6. **Add it to your `doctors.py` file and replace www by partners**, it should look like this:
   ```
   https://partners.doctolib.fr/availabilities.json?visit_motive_ids=123456&agenda_ids=789012&practice_ids=345678&telehealth=false&start_date=2025-06-02&limit=15
   ```

#### Configuration Options:

- **`name`** (optional): Custom name for Discord notifications. If not provided, the system will auto-generate an identifier like `VM123456_AG789012_PR345678`
- **`url`** (required): The complete Doctolib API URL for checking availability

## Usage

### Run the Script

```bash
uv run main.py
```

### Database

The script automatically creates a SQLite database (`sent_slots.db`) to track which notifications have been sent. This ensures:
- No duplicate notifications
- Persistence across script restarts
- Ability to retry failed notifications

## Configuration Examples

### Multiple Doctors at Same Practice
```python
DOCTORS = [
    {
        "name": "Dr. Smith - Cardiology",
        "url": "https://partners.doctolib.fr/availabilities.json?visit_motive_ids=123456&agenda_ids=111111&practice_ids=999999&telehealth=false&start_date=2025-06-02&limit=15"
    },
    {
        "name": "Dr. Jones - Cardiology", 
        "url": "https://partners.doctolib.fr/availabilities.json?visit_motive_ids=123456&agenda_ids=222222&practice_ids=999999&telehealth=false&start_date=2025-06-02&limit=15"
    },
]
```

### Different Appointment Types
```python
DOCTORS = [
    {
        "name": "Dr. Smith - Consultation",
        "url": "https://partners.doctolib.fr/availabilities.json?visit_motive_ids=111111&agenda_ids=123456&practice_ids=999999&telehealth=false&start_date=2025-06-02&limit=15"
    },
    {
        "name": "Dr. Smith - Follow-up",
        "url": "https://partners.doctolib.fr/availabilities.json?visit_motive_ids=222222&agenda_ids=123456&practice_ids=999999&telehealth=false&start_date=2025-06-02&limit=15"
    },
]
```

### Logs

The script provides detailed logging:
- **INFO**: Normal operations and found slots
- **WARNING**: Configuration issues or failed requests
- **ERROR**: Serious problems that need attention

## Requirements

- Python 3.8+
- [uv](https://docs.astral.sh/uv/) package manager
- Discord webhook URL

## Information

Please respect Doctolib's terms of service and rate limits.