"""
Environment Detection Tool for Octopus Framework.

Provides system environment information to prevent platform-specific errors.
"""

import platform
import subprocess
import shutil
import sys
from typing import Dict, Optional


def check_environment() -> Dict[str, any]:
    """
    Detect system environment before executing tasks.
    
    Returns:
        dict: Environment information including:
            - os: Operating system (Windows, Linux, Darwin)
            - python_installed: Path to Python executable or None
            - python_version: Python version string or None
            - package_manager: Available package manager (chocolatey, winget, apt, yum, homebrew, or None)
            - shell: Default shell (powershell, bash, etc.)
    """
    env = {
        "os": platform.system(),  # Windows, Linux, Darwin
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_installed": None,
        "python_version": None,
        "package_manager": None,
        "shell": None
    }
    
    # Check Python installation
    # Try both 'python' and 'python3'
    python_cmd = shutil.which("python") or shutil.which("python3")
    if python_cmd:
        env["python_installed"] = python_cmd
        try:
            result = subprocess.run(
                [python_cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                env["python_version"] = result.stdout.strip() or result.stderr.strip()
        except Exception:
            pass
    
    # Detect package manager based on OS
    if env["os"] == "Windows":
        env["shell"] = "powershell"
        
        if shutil.which("choco"):
            env["package_manager"] = "chocolatey"
        elif shutil.which("winget"):
            env["package_manager"] = "winget"
            
    elif env["os"] == "Linux":
        env["shell"] = "bash"
        
        if shutil.which("apt-get") or shutil.which("apt"):
            env["package_manager"] = "apt"
        elif shutil.which("yum"):
            env["package_manager"] = "yum"
        elif shutil.which("dnf"):
            env["package_manager"] = "dnf"
        elif shutil.which("pacman"):
            env["package_manager"] = "pacman"
            
    elif env["os"] == "Darwin":
        env["shell"] = "bash"
        
        if shutil.which("brew"):
            env["package_manager"] = "homebrew"
    
    return env


def get_install_command(package: str, env_info: Optional[Dict] = None) -> Optional[str]:
    """
    Get the appropriate package installation command for the current system.
    
    Args:
        package: Package name to install (e.g., "python3", "nodejs", "git")
        env_info: Optional pre-fetched environment info from check_environment()
    
    Returns:
        str: Installation command or None if no package manager available
    """
    if env_info is None:
        env_info = check_environment()
    
    pkg_manager = env_info.get("package_manager")
    
    if pkg_manager == "chocolatey":
        return f"choco install {package} -y"
    elif pkg_manager == "winget":
        # Map common package names to winget IDs
        winget_packages = {
            "python3": "Python.Python.3",
            "nodejs": "OpenJS.NodeJS",
            "git": "Git.Git"
        }
        winget_id = winget_packages.get(package, package)
        return f"winget install {winget_id} -e"
    elif pkg_manager == "apt":
        return f"sudo apt-get install -y {package}"
    elif pkg_manager == "yum":
        return f"sudo yum install -y {package}"
    elif pkg_manager == "dnf":
        return f"sudo dnf install -y {package}"
    elif pkg_manager == "homebrew":
        return f"brew install {package}"
    elif pkg_manager == "pacman":
        return f"sudo pacman -S --noconfirm {package}"
    
    return None


def suggest_python_install() -> Dict[str, any]:
    """
    Suggest Python installation command based on current OS.
    
    Returns:
        dict: Contains 'command', 'manual_url', and 'package_manager' information
    """
    env = check_environment()
    install_cmd = get_install_command("python3", env)
    
    result = {
        "os": env["os"],
        "package_manager": env["package_manager"],
        "install_command": install_cmd,
        "manual_url": None
    }
    
    if env["os"] == "Windows":
        result["manual_url"] = "https://www.python.org/downloads/windows/"
    elif env["os"] == "Linux":
        result["manual_url"] = "https://www.python.org/downloads/"
    elif env["os"] == "Darwin":
        result["manual_url"] = "https://www.python.org/downloads/macos/"
    
    return result


if __name__ == "__main__":
    # CLI usage for testing
    import json
    
    if len(sys.argv) > 1 and sys.argv[1] == "suggest-python":
        result = suggest_python_install()
        print(json.dumps(result, indent=2))
    else:
        env = check_environment()
        print(json.dumps(env, indent=2))
