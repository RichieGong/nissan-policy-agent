import streamlit as st
import os
from supabase import create_client, Client

# =====================================================================
# 1. PAGE CONFIGURATION & STYLING
# =====================================================================
st.set_page_config(
    page_title="Nissan Supply Chain Intelligence",
    page_icon="🚘",
    layout="centered"
)

# Custom header banner
st.title("🚘 Nissan Supply Chain Intelligence")
st.markdown(
    "Automated tracking system for global manufacturing nodes, trade policies, "
    "and market trend data. *Updates automatically at 06:00 UTC.*"
)
st.markdown("---")

# =====================================================================
# 2. DATABASE CONNECTION (SUPABASE)
# =====================================================================
# Streamlit reads these from its secure dashboard settings (Secrets)
@st.cache_resource
def init_supabase() -> Client:
    """Initializes and caches the Supabase connection client."""
    # Try local environment variables first, then fallback to Streamlit Cloud secrets
    url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY")
    
    if not url or not key:
        st.error(
            "Missing Database Connection Keys! Please configure 'SUPABASE_URL' "
            "and 'SUPABASE_KEY' in your local environment or Streamlit App Secrets."
        )
        st.stop()
        
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Failed to initialize database client: {str(e)}")
    st.stop()

# =====================================================================
# 3. DATA FETCHING LOGIC
# =====================================================================
def get_chronological_updates():
    try:
        response = (
            supabase
            .from_("policy_updates")
            .select("*")
            .limit(100)
            .execute()
        )
        return response.data
    except Exception as e:
        st.error(f"Database Read Error: {str(e)}")
        return []

# =====================================================================
# 4. DASHBOARD RENDER ENGINE
# =====================================================================
# Fetch rows from the cloud database
records = get_chronological_updates()

# Sidebar controls for your coworker to filter data
st.sidebar.header("Filter Intelligence")
impact_filter = st.sidebar.multiselect(
    "Filter by Category:",
    options=["Crisis", "Trend", "Opportunity"],
    default=["Crisis", "Trend", "Opportunity"]
)

search_query = st.sidebar.text_input("Search Content Keywords:", "").strip().lower()

# Process data display loop
if not records:
    st.info("No policy logs found in the database yet. Wait for the morning scraper run!")
else:
    visible_count = 0
    
    # Loop over database records to generate the vertical chronological timeline
    for record in records:
        # Extract individual row keys
        topic = record.get("topic", "Untitled Update")
        impact = record.get("impact_type", "Trend")
        author = record.get("author", "Anonymous")
        summary = record.get("summary", "")
        # Format database timestamp safely for readability
        timestamp = record.get("created_at", "Unknown Time")
        # Clean up standard ISO string format (e.g., '2026-05-29T15:33:00' -> '2026-05-29 15:33')
        readable_time = timestamp.replace("T", " ").split(".")[0]

        # Apply user filters
        if impact not in impact_filter:
            continue
        if search_query and (search_query not in topic.lower() and search_query not in summary.lower()):
            continue
            
        visible_count += 1

        # Render explicit timeline UI container blocks
        with st.container():
            # Color indicator mapping via an emoji badge
            badge = "🚨" if impact == "Crisis" else "📈" if impact == "Trend" else "💡"
            
            # Header Row
            st.subheader(f"{badge} {topic}")
            
            # Metadata Row
            st.caption(f"**Logged At:** {readable_time} UTC  |  **Origin Identity:** {author}  |  **Impact Class:** {impact}")
            
            # Body Copy Summary
            st.markdown(summary)
            
            # Optional collapsible block to check raw text differences
            if record.get("raw_diff"):
                with st.expander("Show Reference Data / Document Fragment"):
                    st.code(record["raw_diff"], language="text")
                    
            st.markdown("---") #