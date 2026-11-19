// Online play: the BattleGolf Supabase project. Both values are public by design (they ship in the web page);
// the database only allows reads plus the three bg_* functions. Never put the service_role key here.
window.BG_CONFIG = {
  supabaseUrl: "https://xovcpjdlkoitaefbbkrk.supabase.co",
  supabaseKey: "sb_publishable__0EOIA7uWzX-IwX8IUeONA_3hbOpxfB",
  // Google AdSense: ads show at the turn (after hole 9 of 18) and on the final scorecard.
  // Leave these empty and no ad code loads at all. Fill them in from your AdSense account:
  //   adsenseClient: the publisher ID, like "ca-pub-1234567890123456"
  //   adsenseSlot:   the ID of a display ad unit, like "1234567890"
  adsenseClient: "ca-pub-6303118447520739",
  adsenseSlot: "9245116305",
};
