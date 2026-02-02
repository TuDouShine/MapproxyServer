import tkinter as tk

def block_main_interaction(parent, dialog):
    """
    Blocks interaction with the main window (parent) while the dialog is open.
    Applies strict modal behavior:
    1. Sets dialog as transient to parent.
    2. Grabs all events to the dialog.
    3. Disables the parent window (Windows specific visual indication).
    """
    try:
        dialog.transient(parent)
        dialog.grab_set()
        
        # Disable parent window to visually indicate it's blocked (Windows)
        # This prevents clicking on the parent window buttons/inputs
        parent.attributes('-disabled', True)
    except Exception as e:
        print(f"Error blocking main interaction: {e}")

def unblock_main_interaction(parent, dialog=None):
    """
    Restores interaction with the main window.
    1. Re-enables the parent window.
    2. Lifts the parent to ensure it's usable.
    3. Restores focus to the parent.
    """
    try:
        # Re-enable parent window
        parent.attributes('-disabled', False)
        parent.lift()
        parent.focus_force()
        
        if dialog:
            dialog.grab_release()
            
    except Exception as e:
        print(f"Error unblocking main interaction: {e}")
