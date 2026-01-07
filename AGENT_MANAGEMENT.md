# Agent Management Features

## Overview
Added comprehensive agent management capabilities including delete and disable/enable functionality with UI integration.

## New Features

### 1. Delete Agent
- **UI**: Red delete button in agent detail view
- **Confirmation Modal**: Requires user to type "delete" to confirm
- **Backend**: DELETE endpoint at `/agents/{agent_id}`
- **Behavior**:
  - Sends "shutdown" command to agent via WebSocket
  - Deletes agent from database (agents, metrics, process_snapshots, log_occurrences)
  - Removes from connection manager
  - Agent receives shutdown signal and exits

### 2. Disable/Enable Agent
- **UI**: Warning/Success button that toggles state
- **Badge**: Shows "DISABLED" status in header
- **Backend**: POST endpoints at `/agents/{agent_id}/disable` and `/agents/{agent_id}/enable`
- **Behavior**:
  - Disable: Marks agent as disabled, sends "disable" command (stops data collection)
  - Enable: Re-enables agent, allows data collection to resume

## API Endpoints

### DELETE /agents/{agent_id}
Deletes an agent and all associated data.

**Response:**
```json
{
  "success": true,
  "message": "Agent {agent_id} deleted"
}
```

### POST /agents/{agent_id}/disable
Disables an agent (stops accepting data).

**Response:**
```json
{
  "success": true,
  "message": "Agent {agent_id} disabled"
}
```

### POST /agents/{agent_id}/enable
Enables a previously disabled agent.

**Response:**
```json
{
  "success": true,
  "message": "Agent {agent_id} enabled"
}
```

## Database Changes

### agents table
Added `enabled` column:
```sql
enabled INTEGER DEFAULT 1
```

## Agent Commands

The agent now responds to these WebSocket commands:
- `shutdown` - Exit the agent process
- `disable` - Stop data collection (sets ticker to 24 hours)
- `start_stream` - 1s interval (when UI is watching)
- `stop_stream` - 60s interval (passive mode)

## Files Modified

### Backend
- `librarian/main.py` - Added delete, disable, enable endpoints
- `librarian/db.py` - Added delete_agent(), disable_agent(), enable_agent() methods, added enabled column

### Agent
- `scribe/main.go` - Added shutdown and disable command handlers

### Frontend
- `dashboard/src/components/AgentsView.vue` - Added delete/disable buttons and functions
- `dashboard/src/components/ConfirmDeleteModal.vue` - New confirmation modal component

## Utility Script

### delete_all_agents.py
Python script to delete all agents from the database (useful for testing/cleanup).

**Usage:**
```bash
cd /home/tristen/Desktop/LogLibrarian
python3 delete_all_agents.py
```

Prompts for confirmation before deleting.

## UI Flow

1. **Delete Agent**:
   - User clicks "Delete" button
   - Modal appears requiring user to type "delete"
   - On confirmation:
     - Backend sends shutdown signal to agent
     - Agent exits gracefully
     - Database records deleted
     - UI updates to remove agent from list

2. **Disable Agent**:
   - User clicks "Disable" button
   - Agent marked as disabled in database
   - Agent receives disable command and stops collecting metrics
   - Button changes to "Enable" for toggling back

## Testing

After restarting the backend:
1. Select an agent
2. Try disabling it (should show "DISABLED" badge)
3. Try enabling it again
4. Try deleting it (modal should appear, require typing "delete")
5. Confirm - agent should disappear from list
