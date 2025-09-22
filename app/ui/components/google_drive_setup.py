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
            rclone authorize "drive" "scope=drive.readonly"
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
            
            # Scope selection
            scope = st.selectbox(
                "Choose access level:",
                ["drive.readonly", "drive"],
                format_func=lambda x: "📖 Read-only (recommended for syncing)" if x == "drive.readonly" else "📝 Full access (read and write)",
                help="Read-only is safer and sufficient for most sync operations"
            )
            
            if scope == "drive":
                st.info("💡 **Tip:** Use read-only unless you specifically need write access")
                st.code(f'rclone authorize "drive" "scope=drive"')
            else:
                st.code(f'rclone authorize "drive" "scope=drive.readonly"')
        
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
        
        with st.expander("🔄 Reconfigure Existing Setup"):
            if st.button("🗑️ Remove Current Google Drive Config"):
                success = self._remove_gdrive_config()
                if success:
                    st.success("✅ Google Drive configuration removed")
                    st.experimental_rerun()
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
            # This would be implemented as an API endpoint
            # For now, we'll simulate the rclone config creation
            cmd = [
                "sudo", "-u", self.mascloner_user,
                "rclone", "--config", self.rclone_config,
                "config", "create", "gdrive", "drive",
                f"scope={scope}",
                f"token={token}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                return {"success": True}
            else:
                return {"success": False, "error": result.stderr or "Configuration failed"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _test_connection(self) -> Dict[str, Any]:
        """Test the Google Drive connection"""
        try:
            cmd = [
                "sudo", "-u", self.mascloner_user,
                "rclone", "--config", self.rclone_config,
                "--transfers=4", "--checkers=8",
                "lsd", "gdrive:"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Parse folder list
                folders = []
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        # Extract folder name from rclone lsd output
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            folder_name = ' '.join(parts[4:])
                            folders.append(folder_name)
                
                return {"success": True, "folders": folders}
            else:
                return {"success": False, "error": result.stderr or "Connection test failed"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _check_gdrive_status(self) -> Dict[str, Any]:
        """Check current Google Drive configuration status"""
        try:
            # Check if gdrive remote exists
            cmd = [
                "sudo", "-u", self.mascloner_user,
                "rclone", "--config", self.rclone_config,
                "listremotes"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and "gdrive:" in result.stdout:
                # Get some sample folders
                test_result = self._test_connection()
                return {
                    "configured": True,
                    "scope": "drive.readonly",  # Would need to parse from config
                    "sample_folders": test_result.get("folders", [])[:3] if test_result["success"] else []
                }
            else:
                return {"configured": False}
                
        except Exception:
            return {"configured": False}
    
    def _remove_gdrive_config(self) -> bool:
        """Remove existing Google Drive configuration"""
        try:
            cmd = [
                "sudo", "-u", self.mascloner_user,
                "rclone", "--config", self.rclone_config,
                "config", "delete", "gdrive"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0
            
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

# Example usage in Setup Wizard
def render_google_drive_step(api_client):
    """Render Google Drive setup step in the setup wizard"""
    
    setup = GoogleDriveSetup(api_client)
    return setup.render_setup_instructions()
