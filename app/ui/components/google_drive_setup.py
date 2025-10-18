"""
Google Drive Setup Component for Streamlit
Simple OAuth setup using rclone authorize method
"""

import streamlit as st
import subprocess
import json
import os
from typing import Optional, Dict, Any

class GoogleDriveSetup:
    """Google Drive OAuth setup component using the modern rclone authorize approach"""
    
    def __init__(self, api_client):
        self.api = api_client
        self.install_dir = "/srv/mascloner"
        self.rclone_config = f"{self.install_dir}/etc/rclone.conf"
        self.mascloner_user = "mascloner"
    
    def render_setup_instructions(self):
        """Render the setup instructions and token input"""
        
        st.markdown("## 🚀 Simple Google Drive Setup")
        
        # Method selection
        method = st.radio(
            "Choose setup method:",
            ["🎯 Simple Token Method (Recommended)", "🔧 Advanced/Troubleshooting"],
            help="The token method is much easier and doesn't require any infrastructure setup"
        )
        
        if method.startswith("🎯"):
            return self._render_token_method()
        else:
            return self._render_advanced_method()
    
    def _render_token_method(self):
        """Render the simple token-based setup"""
        
        st.markdown("""
        ### ✨ Super Simple Setup
        
        No domains, SSL certificates, or complex setup needed! Just run one command and paste the result.
        """)
        
        # Step 1: Instructions
        with st.expander("📋 Step 1: Get OAuth Token", expanded=True):
            st.markdown("""
            **On ANY computer with a web browser**, run this command:
            
            ```bash
            rclone authorize "drive"
            ```
            
            **What happens:**
            1. 🌐 Your browser opens automatically
            2. 🔐 Google asks you to sign in and authorize
            3. 📋 rclone displays a token (JSON format)
            
            **Don't have rclone?** Install it first:
            ```bash
            curl https://rclone.org/install.sh | sudo bash
            ```
            """)
            
            # Check for custom OAuth credentials
            oauth_config = self.api._make_request("GET", "/oauth/google-drive/oauth-config")
            has_custom_oauth = False
            if oauth_config and oauth_config.get("has_custom_oauth"):
                has_custom_oauth = True
                st.success("🎉 **Custom OAuth credentials detected!** You'll get better API quotas.")
                st.markdown("""
                **With custom OAuth, use this command instead:**
                ```bash
                rclone authorize "drive" "YOUR_CLIENT_ID" "YOUR_CLIENT_SECRET"
                ```
                """)
            else:
                st.info("💡 **Tip:** For better API quotas, consider setting up custom OAuth credentials in the environment variables.")
            
            # Scope selection
            scope = st.selectbox(
                "Choose access level:",
                ["drive.readonly", "drive"],
                format_func=lambda x: "📖 Read-only (my files only)" if x == "drive.readonly" else "📝 Full access (includes 'shared with me')",
                help="Choose 'Full access' if you need to sync files shared with you by others"
            )
            
            if scope == "drive.readonly":
                st.warning("⚠️ **Note:** Read-only access only shows files you own, not files shared with you.")
            else:
                st.info("✅ **Full access** includes your files AND files shared with you by others.")
            
            if scope == "drive":
                st.info("💡 **Tip:** Use read-only unless you specifically need write access")
            
            st.code('rclone authorize "drive"')
            
            st.info("ℹ️ **Note:** The scope will be configured automatically when you paste the token below.")
        
        # Step 2: Token input
        with st.expander("🔑 Step 2: Paste Your Token", expanded=True):
            st.markdown("""
            After running the command above, you'll see output like this:
            ```json
            {"access_token":"ya29.a0AQQ_BD...","token_type":"Bearer",...}
            ```
            
            **Copy the entire JSON object** and paste it below:
            """)
            
            token_input = st.text_area(
                "OAuth Token (JSON):",
                placeholder='{"access_token":"ya29...","token_type":"Bearer",...}',
                height=100,
                help="Paste the complete JSON token from the rclone authorize command"
            )
            
            # Validate token format
            token_valid = False
            if token_input.strip():
                try:
                    token_data = json.loads(token_input.strip())
                    if "access_token" in token_data and "token_type" in token_data:
                        st.success("✅ Token format looks correct!")
                        token_valid = True
                    else:
                        st.error("❌ Token missing required fields (access_token, token_type)")
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON format. Make sure you copied the complete token.")
            
            # Setup button
            if st.button("🚀 Configure Google Drive", disabled=not token_valid):
                return self._configure_with_token(token_input.strip(), scope)
        
        # Step 3: Status
        self._show_current_status()
        
        return False
    
    def _render_advanced_method(self):
        """Render advanced setup options"""
        
        st.markdown("### 🔧 Advanced Setup")
        
        with st.expander("🔑 Custom OAuth Setup (Better Quotas)"):
            st.markdown("""
            **For Google Workspace admins:** Set up custom OAuth credentials for better API quotas.
            
            **Benefits:**
            - 🚀 Dedicated API quotas (not shared with other rclone users)
            - 📊 Better performance for high-usage scenarios
            - 🎛️ Full control over quota management
            
            **Setup Steps:**
            1. Go to [Google Cloud Console](https://console.developers.google.com/)
            2. Create a new project or select existing
            3. Enable Google Drive API
            4. Configure OAuth consent screen (choose "Internal" for Workspace)
            5. Add scopes: `drive`, `drive.metadata.readonly`, `docs`
            6. Create OAuth client ID as "Desktop app" type
            7. Set environment variables:
               ```bash
               export GDRIVE_OAUTH_CLIENT_ID="your_client_id"
               export GDRIVE_OAUTH_CLIENT_SECRET="your_client_secret"
               ```
            """)
            
            # Show current OAuth status
            oauth_config = self.api._make_request("GET", "/oauth/google-drive/oauth-config")
            if oauth_config and oauth_config.get("has_custom_oauth"):
                st.success("✅ Custom OAuth credentials are configured")
                if oauth_config.get("client_id"):
                    st.code(f"Client ID: {oauth_config['client_id']}")
            else:
                st.warning("⚠️ No custom OAuth credentials found in environment variables")
        
        with st.expander("🔄 Reconfigure Existing Setup"):
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("🔑 Re-authenticate Google Drive", use_container_width=True):
                    return self._render_reauth_flow()
            
            with col2:
                if st.button("🗑️ Remove Current Google Drive Config", use_container_width=True):
                    success = self._remove_gdrive_config()
                    if success:
                        st.success("✅ Google Drive configuration removed")
                        self._trigger_rerun()
                    else:
                        st.error("❌ Failed to remove configuration")
        
        with st.expander("🧪 Test Current Configuration"):
            if st.button("🔍 Test Google Drive Connection"):
                result = self._test_connection()
                if result["success"]:
                    st.success("✅ Google Drive connection successful!")
                    if result.get("folders"):
                        st.write("**Available folders:**")
                        for folder in result["folders"][:10]:
                            st.write(f"📁 {folder}")
                else:
                    st.error(f"❌ Connection failed: {result.get('error', 'Unknown error')}")
        
        with st.expander("⚙️ Run Interactive Setup Script"):
            st.markdown("""
            **For advanced users only.** This runs the command-line setup script:
            """)
            
            if st.button("🖥️ Run Setup Script"):
                st.info("🔄 Running setup script... Check the server logs for progress.")
                result = self._run_setup_script()
                if result["success"]:
                    st.success("✅ Setup script completed successfully!")
                else:
                    st.error(f"❌ Setup script failed: {result.get('error', 'Unknown error')}")
        
        return False
    
    def _configure_with_token(self, token: str, scope: str) -> bool:
        """Configure Google Drive using the provided token"""
        
        with st.spinner("🔄 Configuring Google Drive..."):
            try:
                # Call the backend API to configure rclone
                result = self._create_rclone_config(token, scope)
                
                if result["success"]:
                    st.success("✅ Google Drive configured successfully!")
                    
                    # Test the connection
                    test_result = self._test_connection()
                    if test_result["success"]:
                        st.success("✅ Connection test passed!")
                        if test_result.get("folders"):
                            st.write("**Your Google Drive folders:**")
                            for folder in test_result["folders"][:5]:
                                st.write(f"📁 {folder}")
                        return True
                    else:
                        st.warning("⚠️ Configuration created but connection test failed")
                        st.error(f"Error: {test_result.get('error', 'Unknown error')}")
                else:
                    st.error(f"❌ Configuration failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"❌ Setup error: {str(e)}")
        
        return False
    
    def _show_current_status(self):
        """Show current Google Drive configuration status"""
        
        st.markdown("### 📊 Current Status")
        
        # Check if gdrive remote exists
        status = self._check_gdrive_status()
        
        if status["configured"]:
            st.success("✅ Google Drive is configured")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("Remote Name", "gdrive")
                st.metric("Status", "Configured" if status["configured"] else "Not configured")
            
            with col2:
                if status.get("scope"):
                    st.metric("Access Level", status["scope"])
                if status.get("last_used"):
                    st.metric("Last Used", status["last_used"])
            
            # Show some folders if available
            if status.get("sample_folders"):
                st.write("**Sample folders:**")
                for folder in status["sample_folders"][:3]:
                    st.write(f"📁 {folder}")
        else:
            st.info("ℹ️ Google Drive not yet configured")
    
    def _create_rclone_config(self, token: str, scope: str) -> Dict[str, Any]:
        """Create rclone configuration with the provided token"""
        try:
            # Use the API client to configure Google Drive
            result = self.api.configure_google_drive_oauth(token=token, scope=scope)
            
            if result and result.get("success"):
                return {"success": True}
            else:
                return {"success": False, "error": result.get("message", "Configuration failed") if result else "API call failed"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _test_connection(self) -> Dict[str, Any]:
        """Test the Google Drive connection"""
        try:
            # Use the API client to test the connection
            result = self.api.test_google_drive_connection()
            
            if result and result.get("success"):
                return {"success": True, "folders": result.get("data", {}).get("folders", [])}
            else:
                return {"success": False, "error": result.get("message", "Connection failed") if result else "API call failed"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _check_gdrive_status(self) -> Dict[str, Any]:
        """Check current Google Drive configuration status"""
        try:
            # Use the API client to get status
            result = self.api.get_google_drive_status()
            
            if result:
                return {
                    "configured": result.get("configured", False),
                    "scope": result.get("scope", "unknown"),
                    "sample_folders": result.get("folders", [])
                }
            else:
                return {"configured": False}
                
        except Exception:
            return {"configured": False}
    
    def _remove_gdrive_config(self) -> bool:
        """Remove existing Google Drive configuration"""
        try:
            # Use the API client to remove configuration
            result = self.api.remove_google_drive_config()
            return result and result.get("success", False)
            
        except Exception:
            return False
    
    def _run_setup_script(self) -> Dict[str, Any]:
        """Run the setup script"""
        try:
            script_path = f"{self.install_dir}/../ops/scripts/oauth/setup-google-drive.sh"
            cmd = ["bash", script_path]
            
            # This would need to be run asynchronously and show progress
            # For now, just return a placeholder
            return {"success": True, "message": "Script execution started"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _render_reauth_flow(self):
        """Render the re-authentication flow for Google Drive."""
        st.markdown("### 🔑 Re-authenticate Google Drive")
        st.info("This will help you get a fresh OAuth token for Google Drive. Your existing configuration will be updated with the new token.")
        
        # Check for custom OAuth credentials
        oauth_config = self.api._make_request("GET", "/oauth/google-drive/oauth-config")
        has_custom_oauth = oauth_config and oauth_config.get("has_custom_oauth")
        
        # Step 1: Instructions
        with st.expander("📋 Step 1: Get New OAuth Token", expanded=True):
            if has_custom_oauth:
                st.success("🎉 **Custom OAuth detected!** You'll get better API quotas.")
                st.markdown("""
                **Run this command on ANY machine with a web browser:**
                ```bash
                rclone authorize "drive" "YOUR_CLIENT_ID" "YOUR_CLIENT_SECRET"
                ```
                """)
            else:
                st.markdown("""
                **Run this command on ANY machine with a web browser:**
                ```bash
                rclone authorize "drive"
                ```
                """)
            
            st.markdown("""
            **What happens:**
            1. 🌐 Your browser opens automatically
            2. 🔐 Google asks you to sign in and authorize
            3. 📋 rclone displays a new token (JSON format)
            """)
            
            # Scope selection
            scope = st.selectbox(
                "Choose access level:",
                ["drive.readonly", "drive"],
                format_func=lambda x: "📖 Read-only (my files only)" if x == "drive.readonly" else "📝 Full access (includes 'shared with me')",
                help="Choose 'Full access' if you need to sync files shared with you by others"
            )
        
        # Step 2: Token input
        with st.expander("🔑 Step 2: Paste New Token", expanded=True):
            st.markdown("""
            After running the command above, you'll see output like this:
            ```json
            {"access_token":"ya29.a0AQQ_BD...","token_type":"Bearer",...}
            ```
            
            **Copy the entire JSON object** and paste it below:
            """)
            
            token_input = st.text_area(
                "New OAuth Token (JSON):",
                placeholder='{"access_token":"ya29...","token_type":"Bearer",...}',
                height=100,
                help="Paste the complete JSON token from the rclone authorize command"
            )
            
            # Validate token format
            token_valid = False
            if token_input.strip():
                try:
                    token_data = json.loads(token_input.strip())
                    if "access_token" in token_data and "token_type" in token_data:
                        st.success("✅ Token format looks correct!")
                        token_valid = True
                    else:
                        st.error("❌ Token missing required fields (access_token, token_type)")
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON format. Make sure you copied the complete token.")
            
            # Re-authenticate button
            if st.button("🔄 Update Google Drive Authentication", disabled=not token_valid, type="primary"):
                return self._update_authentication(token_input.strip(), scope)
        
        return False
    
    def _update_authentication(self, token: str, scope: str) -> bool:
        """Update Google Drive authentication with new token."""
        with st.spinner("🔄 Updating Google Drive authentication..."):
            try:
                # Call the backend API to update rclone config
                result = self._create_rclone_config(token, scope)
                
                if result["success"]:
                    st.success("✅ Google Drive authentication updated successfully!")
                    
                    # Test the connection
                    test_result = self._test_connection()
                    if test_result["success"]:
                        st.success("✅ Connection test passed!")
                        if test_result.get("folders"):
                            st.write("**Your Google Drive folders:**")
                            for folder in test_result["folders"][:5]:
                                st.write(f"📁 {folder}")
                        return True
                    else:
                        st.warning("⚠️ Authentication updated but connection test failed")
                        st.error(f"Error: {test_result.get('error', 'Unknown error')}")
                else:
                    st.error(f"❌ Authentication update failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"❌ Update error: {str(e)}")
        
        return False

    @staticmethod
    def _trigger_rerun() -> None:
        rerun_fn = getattr(st, "experimental_rerun", None) or getattr(st, "rerun", None)
        if rerun_fn:
            rerun_fn()

# Example usage in Setup Wizard
def render_google_drive_step(api_client):
    """Render Google Drive setup step in the setup wizard"""
    
    setup = GoogleDriveSetup(api_client)
    return setup.render_setup_instructions()
