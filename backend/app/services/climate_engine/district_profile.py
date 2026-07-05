class DistrictProfileService:
    """Service for fetching district profile information."""

    def get_profile(self, state: str, district: str):
        """Return basic profile information for a district."""

        return {
            "state": state,
            "district": district
        }