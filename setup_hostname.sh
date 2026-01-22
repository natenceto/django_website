#!/bin/bash

# Setup script for adding "renew" hostname to /etc/hosts
# This will make "renew" resolve to your local IP

echo "=== Setup hostname for OCPP connections ==="

# Get local IP address
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo "Local IP detected: $LOCAL_IP"
echo "Adding 'renew' to /etc/hosts..."

# Check if entry already exists
if grep -q "renew" /etc/hosts; then
    echo "'renew' already exists in /etc/hosts"
    echo "Current entry:"
    grep "renew" /etc/hosts
else
    # Add entry to /etc/hosts
    echo "$LOCAL_IP renew" | sudo tee -a /etc/hosts
    echo "Added '$LOCAL_IP renew' to /etc/hosts"
fi

# Test the hostname resolution
echo ""
echo "Testing hostname resolution:"
nslookup renew

echo ""
echo "=== Setup complete! ==="
echo "Now you can use 'renew' as hostname in your OCPP connections"
echo "Example: ws://renew:8000/ws/charging_stations/1/"
