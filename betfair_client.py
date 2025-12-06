    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        Returns list of dicts: { 'market_id': str, 'name': str }

        Primary: UK/IRE horse WIN markets containing 'Novice' + 'Hurdle/Hrd'.
        Fallback: If none found, return ALL WIN races today.
        """

        # Dummy mode
        if self.use_dummy:
            print("[BETFAIR] Returning DUMMY novice hurdle markets.")
            return [
                {"market_id": "1.234567891", "name": "Dummy Novice Hurdle 13:30"},
                {"market_id": "1.234567892", "name": "Dummy Novice Hurdle 14:05"},
                {"market_id": "1.234567893", "name": "Dummy Novice Hurdle 15:15"},
            ]

        print("[BETFAIR] Fetching REAL novice hurdle markets for today from API.")

        now_utc = dt.datetime.utcnow()
        start = now_utc
        end_of_day = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)

        base_filter = {
            "eventTypeIds": ["7"],  # Horse Racing
            "marketCountries": ["GB", "IE"],
            "marketTypeCodes": ["WIN"],
            "marketStartTime": {
                "from": start.isoformat() + "Z",
                "to": end_of_day.isoformat() + "Z",
            },
        }

        params = {
            "filter": base_filter,
            "maxResults": 200,
            "marketProjection": ["MARKET_START_TIME", "EVENT", "RUNNER_DESCRIPTION"],
        }

        try:
            result = self._rpc("listMarketCatalogue", params)
        except Exception as e:
            print("[BETFAIR] Error fetching market catalogue:", e)
            return []

        all_today = []
        novice_only = []

        for m in result:
            name = m.get("marketName", "")
            event = m.get("event", {})
            venue = event.get("venue", "")
            open_date = event.get("openDate", "")

            nice_name = f"{venue} {name} ({open_date})".strip()

            entry = {
                "market_id": m["marketId"],
                "name": nice_name,
            }
            all_today.append(entry)

            # Filter novice hurdle
            if "Novice" in name and ("Hurdle" in name or "Hrd" in name):
                novice_only.append(entry)

        print(
            f"[BETFAIR] Found {len(novice_only)} novice hurdles; "
            f"{len(all_today)} total WIN markets today."
        )

        if novice_only:
            return novice_only

        print("[BETFAIR] No novice hurdles — returning ALL WIN races.")
        return all_today
