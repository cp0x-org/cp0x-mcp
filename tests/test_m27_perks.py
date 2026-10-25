"""m27: cp0x community perks in the fact sheet and next to the referral comparison."""

PERK = {
    "name": "Devcon trip",
    "what": ("Every year cp0x gives one of its loyal users a fully paid trip to Devcon: a flight from anywhere in the world, "
             "the hotel and the conference ticket. The winner is drawn at random among the 25 addresses most active in "
             "cp0x activities."),
    "latest": "Devcon 8, Mumbai, November 3-6, 2026",
}


def test_fact_sheet_lists_the_devcon_trip(service):
    perks = service.about_cp0x()["about"]["perks"]
    assert PERK in perks


def test_comparison_carries_the_same_perks(service):
    from cp0x_mcp.about import load_fact_sheet

    assert service.compare_referral_benefits()["cp0x_perks"] == load_fact_sheet()["perks"]
    assert service.compare_referral_benefits(category="perps")["cp0x_perks"] == load_fact_sheet()["perks"]
