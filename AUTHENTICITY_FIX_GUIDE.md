# Fix Authenticity Badges - Implementation Guide

## Problem
Transactions 112, 113, and 114 were marked as "Test / Simulated" in the dashboard, but they were real charging sessions using an actual vehicle with RemoteStartTransaction/RemoteStopTransaction commands from the platform.

## Root Causes Identified
1. **RFID hardcoding**: DEFAULT_TEST_RFID_TAG = "000000010160897" was hardcoded as a test RFID, but this is the actual RFID of station TACW22-G0136
2. **RemoteStart marking**: All RemoteStartTransaction sessions were automatically marked with session_source="simulated", regardless of whether the station is real or simulated

## Changes Made

### 1. File: `/home/natenceto/Main/Work/Projects/RENEW/github/django_website/renew_website/apps/charging_stations/services/exports.py`

**Change 1.1 - Line 13**: Disabled DEFAULT_TEST_RFID_TAG
```python
# BEFORE:
DEFAULT_TEST_RFID_TAG = "000000010160897"

# AFTER:
DEFAULT_TEST_RFID_TAG = None  # Disabled: was "000000010160897" but this is a real station RFID
```

**Change 1.2 - Lines 115-147**: Added platform source check in _is_simulated_station()
```python
# BEFORE:
def _is_simulated_station(tx: Transaction) -> bool:
    # ... other checks ...
    if source in {"simulator", "simulation", "simulated"}:
        return True
    # ...

# AFTER:
def _is_simulated_station(tx: Transaction) -> bool:
    # ... other checks ...
    # Platform-commanded sessions (RemoteStart) are NOT simulated; they are real charging
    if source == "platform":
        return False
    if source in {"simulator", "simulation", "simulated"}:
        return True
    # ...
```

### 2. File: `/home/natenceto/Main/Work/Projects/RENEW/github/django_website/renew_website/apps/charging_stations/consumers.py`

**Change 2.1 - Lines 2165-2202**: Updated RemoteStartTransaction logic
```python
# BEFORE (lines 2177-2178):
if any(signature in runtime_signature for signature in {"simulator", "simulation", "avt-express"}):
    session_context.setdefault("runtime_type", "simulated")
    session_context.setdefault("session_source", "simulated")

# AFTER (lines 2177-2183):
if any(signature in runtime_signature for signature in {"simulator", "simulation", "avt-express"}):
    session_context.setdefault("runtime_type", "simulated")
    session_context.setdefault("session_source", "simulated")
else:
    # Real charging station: RemoteStart is platform-commanded but real charging
    session_context.setdefault("session_source", "platform")
    session_context.setdefault("runtime_type", "real")
```

### 3. Helper Script: `/home/natenceto/Main/Work/Projects/RENEW/github/django_website/fix_transaction_authenticity.py`

Created a Django management script to fix existing transactions (112, 113, 114).

## How to Apply Fixes

### For New Transactions (Automatic)
After deploying the code changes, all new RemoteStartTransaction sessions will be correctly marked as "Real Charge" (not "Test / Simulated").

### For Existing Transactions (Manual Fix)
To fix transactions 112, 113, 114 that are currently showing "Test / Simulated":

**Option 1: Using the provided script (when Docker is running)**
```bash
cd /home/natenceto/Main/Work/Projects/RENEW/github/django_website
docker-compose up -d
python manage.py shell < fix_transaction_authenticity.py
```

**Option 2: Using raw SQL (PostgreSQL)**
```sql
-- Update transaction 112
UPDATE charging_stations_metervalue 
SET data = jsonb_set(
    data,
    '{session_context,session_source}',
    '"platform"'::jsonb
)
WHERE transaction_id = 112 AND data->'session_context'->>'session_source' = 'simulated';

-- Update transaction 113
UPDATE charging_stations_metervalue 
SET data = jsonb_set(
    data,
    '{session_context,session_source}',
    '"platform"'::jsonb
)
WHERE transaction_id = 113 AND data->'session_context'->>'session_source' = 'simulated';

-- Update transaction 114
UPDATE charging_stations_metervalue 
SET data = jsonb_set(
    data,
    '{session_context,session_source}',
    '"platform"'::jsonb
)
WHERE transaction_id = 114 AND data->'session_context'->>'session_source' = 'simulated';

-- Verify changes
SELECT id, data->'session_context'->>'session_source' as session_source
FROM charging_stations_metervalue
WHERE transaction_id IN (112, 113, 114);
```

**Option 3: Django Admin Panel (Manual)**
1. Go to `/admin/charging_stations/transaction/`
2. For each transaction (112, 113, 114):
   - Open the transaction
   - Find the MeterValue records in the inline section
   - Clear browser cache and refresh to see updated badges
3. Refresh the dashboard to see updated authenticity badges

## Expected Results

### Before Fix
- Transaction 112: "Test / Simulated" badge
- Transaction 113: "Test / Simulated" badge  
- Transaction 114: "Test / Simulated" badge

### After Fix
- Transaction 112: "Real Charge" badge (data quality-dependent, likely "Real Charge")
- Transaction 113: "Real Charge" badge
- Transaction 114: "Real Charge" badge

## Verification

After applying the fix, verify in the dashboard:
1. Navigate to the transactions table
2. Check that TX 112, 113, 114 now show "Real Charge" (or other authenticity based on data quality)
3. The "Authenticity" column should no longer show "Simulated" for these sessions

## Technical Details

The authenticity classification logic now works as follows:

1. **Check if station is simulated**: station.runtime_environment == "simulated"
2. **Check session source**:
   - If `session_source == "platform"` → NOT simulated (real charging)
   - If `session_source` in {"simulated", "simulator", "simulation"} → IS simulated
3. **Check RFID**: Only if it matches a real test RFID (now None/disabled)
4. **Check model signature**: Only if matches simulator models

For TACW22-G0136 real charging with RemoteStart:
- `session_source = "platform"` (new logic)
- This immediately returns `False` in `_is_simulated_station()`
- Session is classified as "Real Charge" if meter data exists

## File Changes Summary

| File | Lines | Change Type | Status |
|------|-------|-------------|--------|
| exports.py | 13 | DEFAULT_TEST_RFID_TAG = None | ✅ Completed |
| exports.py | 115-147 | Add platform check | ✅ Completed |
| consumers.py | 2177-2183 | Set platform/real for real stations | ✅ Completed |
| fix_transaction_authenticity.py | (new) | Helper script for existing TX | ✅ Created |
