import streamlit as st

st.set_page_config(
    page_title="MORT",
    page_icon="🤖",
    layout="centered",
)

st.title("🤖 MORT (Mutation-Guided Oracle Refinement Testing")
# st.caption("Edit `app.py` and save to see changes instantly.")

# ---- Sidebar ----
st.sidebar.header("Controls")
name = st.sidebar.text_input("Your name", value="Pranav")
show_debug = st.sidebar.toggle("Show debug", value=False)

# ---- Main content ----
st.write(f"Hello, **{name}** 👋")

col1, col2 = st.columns(2)
with col1:
    n = st.number_input("Pick a number", min_value=0, max_value=100, value=7, step=1)
with col2:
    mode = st.selectbox("Mode", ["A", "B", "C"], index=0)

st.divider()

if st.button("Do something"):
    st.success(f"Done! Number={n}, Mode={mode}")

# ---- Debug / state ----
if show_debug:
    st.subheader("Debug")
    st.json(
        {
            "name": name,
            "n": n,
            "mode": mode,
            "session_state": dict(st.session_state),
        }
    )
