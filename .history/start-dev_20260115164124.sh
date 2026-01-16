#!/bin/bash
# Start SkyPilot development environment for Yotta integration

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== SkyPilot Yotta Development Environment ===${NC}"
echo ""

# Activate virtual environment
if [ -d "venv-dev" ]; then
    echo -e "${GREEN}✓${NC} Activating development virtual environment..."
    source venv-dev/bin/activate
else
    echo "Error: venv-dev not found. Run 'python3 -m venv venv-dev' first."
    exit 1
fi

# Show environment info
echo ""
echo -e "${BLUE}Environment Info:${NC}"
echo "  Python: $(which python)"
echo "  SkyPilot: $(pip show skypilot | grep Version | awk '{print $2}')"
echo "  Mode: Development (editable install)"
echo ""

# Check Yotta catalog
if [ -f "$HOME/.sky/catalogs/v7/yotta/vms.csv" ]; then
    echo -e "${GREEN}✓${NC} Yotta catalog found: ~/.sky/catalogs/v7/yotta/vms.csv"
    echo "  Instance types: $(tail -n +2 ~/.sky/catalogs/v7/yotta/vms.csv | wc -l | tr -d ' ')"
else
    echo "⚠️  Yotta catalog not found. Create ~/.sky/catalogs/v7/yotta/vms.csv"
fi

# Check Yotta credentials
if [ -f "$HOME/.yotta/credentials" ]; then
    echo -e "${GREEN}✓${NC} Yotta credentials found"
else
    echo "⚠️  Yotta credentials not found at ~/.yotta/credentials"
    echo "   Create file with:"
    echo "   userId=<your-user-id>"
    echo "   apikey=<your-api-key>"
fi

echo ""
echo -e "${BLUE}Ready to develop!${NC} Try:"
echo "  sky launch --cloud yotta examples/minimal.yaml"
echo "  sky show-gpus --cloud yotta"
echo ""
echo "To exit: type 'deactivate'"

# Start interactive shell
exec $SHELL
