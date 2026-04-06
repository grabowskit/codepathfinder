#!/bin/bash
# update-memory.sh - Update CodePathfinder development memory after chat sessions
#
# Usage:
#   ./scripts/update-memory.sh                    # Interactive mode
#   ./scripts/update-memory.sh --quick "summary"  # Quick append mode

set -e

# Set MEMORY_DIR to your Claude Code project memory path
# Example: $HOME/.claude/projects/-path-to-your-project/memory
MEMORY_DIR="${CLAUDE_MEMORY_DIR:-$HOME/.claude/projects/$(basename $(pwd))/memory}"
MEMORY_INDEX="$MEMORY_DIR/MEMORY.md"
MEMORY_BACKUP_DIR="$MEMORY_DIR/.backups"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Ensure memory directory exists
if [ ! -d "$MEMORY_DIR" ]; then
    echo -e "${RED}Error: Memory directory not found at $MEMORY_DIR${NC}"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$MEMORY_BACKUP_DIR"

# Function to backup a file
backup_file() {
    local file="$1"
    if [ -f "$file" ]; then
        local filename=$(basename "$file")
        local timestamp=$(date +%Y%m%d_%H%M%S)
        cp "$file" "$MEMORY_BACKUP_DIR/${filename}.${timestamp}.bak"
        echo -e "${GREEN}✓${NC} Backed up to ${MEMORY_BACKUP_DIR}/${filename}.${timestamp}.bak"
    fi
}

# Function to list existing memory files
list_memory_files() {
    echo -e "\n${BOLD}Existing memory files:${NC}"
    local i=1
    while IFS= read -r line; do
        if [[ "$line" =~ ^\-[[:space:]]\[(.+)\]\((.+)\)[[:space:]]—[[:space:]](.+)$ ]]; then
            local title="${BASH_REMATCH[1]}"
            local file="${BASH_REMATCH[2]}"
            local desc="${BASH_REMATCH[3]}"
            echo -e "${BLUE}$i${NC}. $title ${YELLOW}($file)${NC}"
            echo "   $desc"
            i=$((i + 1))
        fi
    done < <(grep -E '^\- \[' "$MEMORY_INDEX")
    echo -e "${BLUE}$i${NC}. ${GREEN}[Create new memory file]${NC}"
    echo ""
}

# Function to show memory types
show_memory_types() {
    echo -e "\n${BOLD}Memory types:${NC}"
    echo -e "${BLUE}1${NC}. ${GREEN}user${NC} - Information about user preferences, role, knowledge"
    echo -e "${BLUE}2${NC}. ${GREEN}feedback${NC} - Guidance about how to approach work (what to avoid/keep doing)"
    echo -e "${BLUE}3${NC}. ${GREEN}project${NC} - Ongoing work, goals, initiatives, bugs, incidents"
    echo -e "${BLUE}4${NC}. ${GREEN}reference${NC} - Pointers to external systems/resources"
    echo ""
}

# Quick mode for simple appends to MEMORY.md
quick_mode() {
    local summary="$1"
    local date=$(date +%Y-%m-%d)

    echo -e "${BOLD}Quick Memory Update${NC}"
    echo -e "Adding entry to MEMORY.md main section..."
    echo ""

    # Backup first
    backup_file "$MEMORY_INDEX"

    # Determine section (ask user)
    echo "Which section should this go in?"
    echo "1. Production Environment"
    echo "2. Deployment"
    echo "3. Architecture"
    echo "4. Local Dev Notes"
    echo "5. Other (I'll place it for you)"
    read -p "Choice [1-5]: " section_choice

    local section_title
    case $section_choice in
        1) section_title="Production Environment" ;;
        2) section_title="Deployment" ;;
        3) section_title="Architecture" ;;
        4) section_title="Local Dev Notes" ;;
        *) section_title="Other" ;;
    esac

    echo ""
    echo -e "${YELLOW}Summary to add:${NC} $summary"
    echo -e "${YELLOW}Section:${NC} $section_title"
    echo -e "${YELLOW}Date:${NC} $date"
    echo ""
    read -p "Proceed? [y/N] " confirm

    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Cancelled."
        exit 0
    fi

    # Add to MEMORY.md
    echo "- **$summary** (added $date)" >> "$MEMORY_INDEX"

    echo -e "\n${GREEN}✓ Memory updated!${NC}"
    echo "Review: $MEMORY_INDEX"
}

# Interactive mode
interactive_mode() {
    echo -e "${BOLD}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║   CodePathfinder Memory Update Tool           ║${NC}"
    echo -e "${BOLD}╚════════════════════════════════════════════════╝${NC}"
    echo ""

    # Step 1: What did you work on?
    echo -e "${BOLD}Step 1: Chat Session Summary${NC}"
    echo "What did you work on in this session?"
    echo "(Describe the feature, bug fix, investigation, or changes made)"
    echo ""
    read -p "> " session_summary
    echo ""

    # Step 2: What's important to remember?
    echo -e "${BOLD}Step 2: Key Learnings${NC}"
    echo "What should be remembered for future sessions?"
    echo "(e.g., gotchas discovered, decisions made, patterns to follow)"
    echo ""
    read -p "> " key_learnings
    echo ""

    # Step 3: Choose memory type
    show_memory_types
    read -p "Select memory type [1-4]: " type_choice

    local memory_type
    case $type_choice in
        1) memory_type="user" ;;
        2) memory_type="feedback" ;;
        3) memory_type="project" ;;
        4) memory_type="reference" ;;
        *) memory_type="project" ;;
    esac
    echo ""

    # Step 4: Choose file to update or create new
    list_memory_files
    read -p "Select file to update (or number for new file): " file_choice

    local memory_file
    local is_new=false

    # Parse selection
    if [[ "$file_choice" =~ ^[0-9]+$ ]]; then
        local selected_file=$(grep -E '^\- \[' "$MEMORY_INDEX" | sed -n "${file_choice}p" | sed -E 's/.*\(([^)]+)\).*/\1/')

        if [ -z "$selected_file" ]; then
            # Creating new file
            is_new=true
            echo ""
            read -p "New memory file name (e.g., new_feature.md): " new_filename
            memory_file="$MEMORY_DIR/$new_filename"
        else
            memory_file="$MEMORY_DIR/$selected_file"
        fi
    else
        echo "Invalid selection. Exiting."
        exit 1
    fi

    echo ""

    # Step 5: If new file, get metadata
    local memory_name
    local memory_description

    if [ "$is_new" = true ]; then
        echo -e "${BOLD}New Memory File Metadata${NC}"
        read -p "Memory name (for frontmatter): " memory_name
        read -p "One-line description: " memory_description
        echo ""
    fi

    # Step 6: Generate update content
    local date=$(date +%Y-%m-%d)
    local update_content=""

    if [ "$memory_type" = "feedback" ] || [ "$memory_type" = "project" ]; then
        echo -e "${BOLD}Additional Context${NC}"
        read -p "Why is this important? (for **Why:** section): " why_context
        read -p "How should this be applied? (for **How to apply:** section): " how_context
        echo ""

        update_content="## $session_summary (added $date)

$key_learnings

**Why:** $why_context

**How to apply:** $how_context"
    else
        update_content="## $session_summary (added $date)

$key_learnings"
    fi

    # Step 7: Preview and confirm
    echo -e "${BOLD}Preview:${NC}"
    echo -e "${YELLOW}────────────────────────────────────────────${NC}"
    if [ "$is_new" = true ]; then
        echo "Creating new file: $memory_file"
        echo ""
        echo "---"
        echo "name: $memory_name"
        echo "description: $memory_description"
        echo "type: $memory_type"
        echo "---"
        echo ""
    else
        echo "Updating existing file: $memory_file"
        echo ""
    fi
    echo "$update_content"
    echo -e "${YELLOW}────────────────────────────────────────────${NC}"
    echo ""

    read -p "Proceed with update? [y/N] " confirm

    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Cancelled."
        exit 0
    fi

    # Step 8: Backup and write
    if [ -f "$memory_file" ]; then
        backup_file "$memory_file"
    fi

    if [ "$is_new" = true ]; then
        # Create new file with frontmatter
        cat > "$memory_file" << EOF
---
name: $memory_name
description: $memory_description
type: $memory_type
---

$update_content
EOF

        # Add to MEMORY.md index
        backup_file "$MEMORY_INDEX"
        local filename=$(basename "$memory_file")
        echo "- [$memory_name]($filename) — $memory_description" >> "$MEMORY_INDEX"

        echo -e "\n${GREEN}✓ Created new memory file!${NC}"
        echo "  File: $memory_file"
        echo "  Added to: $MEMORY_INDEX"
    else
        # Append to existing file
        echo "" >> "$memory_file"
        echo "$update_content" >> "$memory_file"

        echo -e "\n${GREEN}✓ Memory updated!${NC}"
        echo "  File: $memory_file"
    fi

    echo ""
    echo -e "${GREEN}${BOLD}Done!${NC}"
}

# Main
if [ "$1" = "--quick" ]; then
    if [ -z "$2" ]; then
        echo "Usage: $0 --quick \"summary text\""
        exit 1
    fi
    quick_mode "$2"
else
    interactive_mode
fi
