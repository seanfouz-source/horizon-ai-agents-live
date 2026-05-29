from app.campaigns import campaign_video_catalog, campaign_video_path, campaign_video_public_url


def test_campaign_video_urls_are_public_mp4s():
    assert campaign_video_public_url("wholesale") == "https://horizon-ai-agents.onrender.com/media/campaigns/wholesale.mp4"
    assert (
        campaign_video_public_url("retail")
        == "https://horizon-ai-agents.onrender.com/media/campaigns/ebay-retail-store.mp4"
    )


def test_campaign_video_files_are_packaged():
    assert campaign_video_path("wholesale").exists()
    assert campaign_video_path("ebay-retail-store").exists()


def test_campaign_video_catalog_marks_files_available():
    catalog = campaign_video_catalog()

    assert {video["slug"] for video in catalog} == {"wholesale", "ebay-retail-store"}
    assert all(video["file_exists"] for video in catalog)
