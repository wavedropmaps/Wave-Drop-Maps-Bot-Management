# Train User & Validation Implementation Design

## 1. Overview
Implement a new "Train a User" feature in the Head of Staff panel that mirrors the "Add Duty" modal. When submitted, it sends a webhook/API request to the backend, which will then DM the user a specific training server invite link based on the selected duty. Additionally, implement User ID validation across both modals.

## 2. UI/UX Flow
- **New Button:** A new `✨ Train a User` button will be placed in the Head of Staff actions bar (next to "Add a staff member to duty").
- **Modal:** Clicking it opens a premium modal specifically for training.
- **Dropdown Options:**
  - Surge Route Maker
  - Tips & Tricks Helper
  - Loot Route Maker
  - Map Request (Unique to Training)
- **Input:** Discord User ID field.

## 3. Validation Logic (Frontend vs Backend)
- **Frontend Validation:** We will add regex checking to ensure the User ID consists only of numbers and is between 17-19 characters long (standard Discord snowflake). If it fails, the UI immediately shows a toast error: "Invalid Discord User ID format."
- **Backend Validation Requirement:** The frontend cannot verify if a user *actually exists* or if their *DMs are open*. The backend must handle these checks and return a `400` or `404` status so the UI can display "Error: User not found or DMs are closed."

## 4. Proposed Backend Hook
- **Endpoint:** `/api/admin/staff/train`
- **Payload Structure:**
  ```json
  {
    "training_type": "add_surge",
    "user_id": "123456789012345678"
  }
  ```
- **Backend Responsibility:** The Python backend will map `training_type` to the specific Discord invite link, format the DM message, attempt to send it, and return success/failure to the UI.

## 5. Security & Edge Cases
- **Missing Roles:** The UI already restricts access to Head of Staff.
- **DM Failures:** The UI will handle error responses (e.g., `500` or `403`) from the backend if the DM cannot be sent due to privacy settings, alerting the admin that the user must be contacted manually.
