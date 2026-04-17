

# HOW TO GET GMAIL APP PASSWORD:
# 1. Go to your Google Account → Security
# 2. Enable 2-Step Verification
# 3. Go to Security → App passwords
# 4. Select "Mail" and "Windows Computer"
# 5. Copy the 16-character password and paste above


# ============================================================
# STEP 2: Add this helper function to views.py (near the top)
# ============================================================






# ============================================================
# STEP 3: Call the function in your views
# ============================================================

# In book_appointment view — after appointment is saved:
# send_appointment_email(appointment, 'booked')

# In cancel_appointment view — after cancellation:
# send_appointment_email(appointment, 'cancelled')

# In complete_appointment view — after completion:
# send_appointment_email(appointment, 'completed')


# ============================================================
# STEP 4: Add this URL to urls.py for the calendar
# ============================================================

# path('availability/calendar/', views.availability_calendar, name='availability_calendar'),


# ============================================================
# STEP 5: Add this view to views.py for the calendar
# ============================================================

