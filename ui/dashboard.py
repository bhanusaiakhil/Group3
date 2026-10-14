"""BONUS dashboard: demand, utilisation, due-soon/overdue alerts.  SKELETON - P1 builds after core works."""
import streamlit as st

from ui import components as ui


def render(user: dict) -> None:
    ui.section("Insights", "Demand, copy utilisation and due-soon alerts for the library team.")
    st.info("Coming soon – built once the core lending flow is complete (owner: P1).", icon="📊")
