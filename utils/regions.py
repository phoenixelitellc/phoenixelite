
REGION_STATES = {
    "west": ["AK","AZ","CA","CO","HI","ID","MT","NV","NM","OR","UT","WA","WY"],
    "midwest": ["IL","IN","IA","KS","MI","MN","MO","NE","ND","OH","SD","WI"],
    "south": ["AL","AR","DC","DE","FL","GA","KY","LA","MD","MS","NC","OK","SC","TN","TX","VA","WV"],
    "northeast": ["CT","ME","MA","NH","NJ","NY","PA","RI","VT"],
}
REGION_SYNONYMS = {
    "pnw":"west","west coast":"west","pacific northwest":"west",
    "southwest":"west","southeast":"south","mid-west":"midwest",
    "north east":"northeast","north-east":"northeast"
}
STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado",
    "CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho",
    "IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana",
    "ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi",
    "MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey",
    "NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma",
    "OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota",
    "TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington",
    "WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","DC":"District of Columbia"
}
def normalize_region(region: str) -> str:
    if not region: return ""
    r = region.strip().lower()
    r = REGION_SYNONYMS.get(r, r)
    return r if r in REGION_STATES else ""
