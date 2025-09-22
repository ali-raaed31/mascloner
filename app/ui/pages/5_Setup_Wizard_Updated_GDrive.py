"""
Updated Setup Wizard with New Google Drive OAuth
Replace the existing Google Drive step with this implementation
"""

import streamlit as st
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import APIClient
from components.google_drive_setup import GoogleDriveSetup

# Initialize API client
api = APIClient()

def render_google_drive_step():
    """Render the updated Google Drive setup step"""
    
    st.markdown("## 📁 Google Drive Configuration")
    
    # Initialize the Google Drive setup component
    gdrive_setup = GoogleDriveSetup(api)
    
    # Render the setup interface
    success = gdrive_setup.render_setup_instructions()
    
    if success:
        st.success("✅ Google Drive configured successfully!")
        return True
    
    return False

# Example of how to integrate into the existing Setup Wizard:
def updated_setup_wizard():
    """Updated setup wizard with new Google Drive flow"""
    
    # ... existing setup wizard code ...
    
    # Step 2: Google Drive Setup (replace existing step)
    if st.session_state.setup_step == 2:
        st.header("📁 Step 2: Google Drive Setup")
        
        if render_google_drive_step():
            # Move to next step
            col1, col2, col3 = st.columns([1, 1, 1])
            with col3:
                if st.button("Next: Nextcloud Setup →", type="primary"):
                    st.session_state.setup_step = 3
                    st.experimental_rerun()
        
        # Back button
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("← Back"):
                st.session_state.setup_step = 1
                st.experimental_rerun()

# Usage in the main Setup Wizard file:
# Replace the existing Google Drive step with:
# success = render_google_drive_step()
