document.addEventListener('DOMContentLoaded', () => {
    // Use the same WebSocket connection from base.html instead of creating a new one
    // The WebSocket connection is already managed in base.html
    
    // Listen for custom events that might be triggered by the base.html WebSocket
    document.addEventListener('station-update', (event) => {
        const data = event.detail;
        
        // Handle different types of updates
        if (data.type === 'status_update' && data.data) {
            const status = data.data;
            
            // Update any specific UI elements that aren't handled by base.html
            // For example, update the stations table if it exists
            const stationsTable = document.querySelector('#stations-table tbody');
            if (stationsTable) {
                // This is a simplified example - you'll want to update this to match your actual table structure
                // and data format
                console.log('Received station status update:', status);
            }
        }
    });
    
    // If you need to send messages to the server, you can use a custom event
    // that the base.html WebSocket will listen for
    window.sendWebSocketMessage = function(message) {
        const event = new CustomEvent('send-websocket-message', { detail: message });
        document.dispatchEvent(event);
    };
});