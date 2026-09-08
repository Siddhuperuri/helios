"""Who is asking, and therefore what to ask them.

The interview is data, not code, and that is the whole point of this module. §8 requires
the questions to adapt to the user, §12 requires every technical question to offer a way
out for someone who does not know the answer, §33 requires strings to be localisable, and
§34 requires the flow to remain answerable by voice later. All four are satisfied by the
same decision: describe the interview declaratively, serve it from the API, and let the
frontend render whatever it is given.

The alternative — a wizard hardcoded as React components — fails every one of those. Adding
Telugu would mean editing components; adding a voice front end would mean reimplementing
the whole flow; and the "I don't know" branch would be at the mercy of whoever wrote each
form field.

Every question therefore carries: a written prompt, a spoken form for a future voice agent,
help text in plain language, and — wherever the answer is technical — an explicit escape
route saying what happens if the user does not know.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.estimate import assumptions as _A

QuestionKind = Literal[
    "single_choice",
    "multi_choice",
    "number",
    "currency",
    "area",
    "location",
    "equipment_list",
    "pump_list",
    "boolean",
    "text",
    "info",
]


# --------------------------------------------------------------------------------------
# User types (§6)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class UserTypeOption:
    key: str
    title: str
    description: str
    icon: str
    # Spoken forms a future voice agent should map to this option (§34). Not exhaustive,
    # and not a substitute for real intent classification — a starting vocabulary.
    synonyms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "synonyms": list(self.synonyms),
        }


USER_TYPES: tuple[UserTypeOption, ...] = (
    UserTypeOption(
        "home", "Home",
        "Reduce electricity bills and power my home.",
        "home",
        ("home", "house", "my house", "residence", "apartment", "flat", "household"),
    ),
    UserTypeOption(
        "farm", "Farm / Agriculture",
        "Power pumps, irrigation, farm buildings and agricultural equipment.",
        "sprout",
        ("farm", "agriculture", "field", "pump", "water pump", "borewell", "irrigation",
         "crops", "farming", "dairy", "poultry"),
    ),
    UserTypeOption(
        "shop", "Shop / Small Business",
        "Power a shop, office, clinic or small commercial space.",
        "store",
        ("shop", "store", "small business", "clinic", "salon", "office", "restaurant"),
    ),
    UserTypeOption(
        "commercial", "Commercial / Industrial",
        "Power a larger facility, factory, warehouse or infrastructure.",
        "factory",
        ("factory", "industry", "industrial", "warehouse", "plant", "commercial", "mill"),
    ),
    UserTypeOption(
        "institution", "School / Institution",
        "Power a school, college, hospital or public facility.",
        "school",
        ("school", "college", "university", "hospital", "institution", "temple", "government"),
    ),
    UserTypeOption(
        "exploring", "Just Exploring",
        "I want to understand my solar potential.",
        "compass",
        ("just looking", "exploring", "curious", "not sure", "just checking"),
    ),
)


# --------------------------------------------------------------------------------------
# Goal (asked immediately after user type)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class GoalOption:
    key: str
    title: str
    description: str
    icon: str
    synonyms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "synonyms": list(self.synonyms),
        }


# This is the question that decides the shape of everything after it, which is why it is
# asked second and in plain language.
#
# The distinction it draws is not cosmetic: for somebody who already owns an array, the
# panel count is a *measurement* and capacity is derived from it. For somebody planning
# one, capacity is *derived* from their demand and space, and the panel count is the
# recommendation that falls out. Asking "how many panels?" of the second group before
# knowing what they need would be asking them to answer the question they came to ask.
GOALS: tuple[GoalOption, ...] = (
    GoalOption(
        "existing", "I already have solar panels",
        "Find out what the system you already own should be producing.",
        "sun",
        ("i have solar", "already installed", "existing", "already have panels",
         "my panels", "installed already"),
    ),
    GoalOption(
        "install", "I want to install solar",
        "Work out the right system size and how many panels that is.",
        "layers",
        ("want to install", "planning", "new system", "thinking about solar",
         "want solar", "how many panels do i need"),
    ),
    GoalOption(
        "compare", "I'm comparing options",
        "Put several system sizes side by side before deciding.",
        "sliders",
        ("comparing", "compare", "options", "quotes", "which size", "deciding"),
    ),
)


# --------------------------------------------------------------------------------------
# Modes (§7)
# --------------------------------------------------------------------------------------

MODES: tuple[dict[str, Any], ...] = (
    {
        "key": "quick",
        "title": "Quick Estimate",
        "description": "Get a useful solar estimate with only a few simple questions.",
        "duration": "About 1–2 minutes",
        "suited_to": "Homeowners, farmers, and anyone new to solar.",
        "icon": "zap",
    },
    {
        "key": "detailed",
        "title": "Detailed Analysis",
        "description": "Provide technical information for a more precise engineering estimate.",
        "duration": "About 5–10 minutes",
        "suited_to": "Engineers, consultants, EPC companies and commercial projects.",
        "icon": "sliders",
    },
)


# --------------------------------------------------------------------------------------
# Questions
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Option:
    value: str
    label: str
    description: str = ""
    icon: str | None = None
    synonyms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "synonyms": list(self.synonyms),
        }


@dataclass(frozen=True)
class Question:
    id: str
    field: str
    kind: QuestionKind
    prompt: str
    spoken_prompt: str = ""
    help_text: str = ""
    options: tuple[Option, ...] = ()
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    required: bool = False
    # §12: the escape route. ``unknown_label`` is what the button says; ``unknown_effect``
    # tells the user, honestly, what happens to their estimate if they take it.
    unknown_label: str | None = None
    unknown_effect: str | None = None
    depends_on: dict[str, Any] | None = None
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "field": self.field,
            "kind": self.kind,
            "prompt": self.prompt,
            "spoken_prompt": self.spoken_prompt or self.prompt,
            "help_text": self.help_text,
            "options": [o.to_dict() for o in self.options],
            "unit": self.unit,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "required": self.required,
            "unknown_label": self.unknown_label,
            "unknown_effect": self.unknown_effect,
            "depends_on": self.depends_on,
            "group": self.group,
        }


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    subtitle: str = ""
    questions: tuple[Question, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "questions": [q.to_dict() for q in self.questions],
        }


# ------------------------------------------------------------------ shared questions

LOCATION = Question(
    id="location",
    field="location",
    kind="location",
    prompt="Where will the solar panels be?",
    spoken_prompt="Where are you? You can tell me your village, town or city.",
    help_text=(
        "We use your location to look up years of real weather and sunlight data for that "
        "exact spot."
    ),
    required=True,
    group="location",
)

CONSUMPTION_METHOD = Question(
    id="consumption_method",
    field="consumption_method",
    kind="single_choice",
    prompt="How much electricity do you use?",
    spoken_prompt="Do you know your electricity bill, or how many units you use?",
    help_text="Any of these works. Pick whichever you can answer most easily.",
    options=(
        Option("bill", "I know my electricity bill",
               "Tell us roughly what you pay each month.", "receipt",
               ("bill", "i know my bill", "i pay", "rupees a month")),
        Option("units", "I know my units (kWh)",
               "The number of units on your bill each month.", "gauge",
               ("units", "kwh", "kilowatt hours", "i know my units")),
        Option("equipment", "Help me work it out",
               "Answer a few questions about what you run.", "list",
               ("i don't know", "not sure", "help me", "work it out", "estimate for me")),
    ),
    required=True,
    group="consumption",
)

MONTHLY_BILL = Question(
    id="monthly_bill",
    field="monthly_bill",
    kind="currency",
    prompt="Roughly how much is your monthly electricity bill?",
    spoken_prompt="About how much is your electricity bill each month?",
    help_text="An average across the year is fine. We will show what that implies in units.",
    min_value=1,
    depends_on={"consumption_method": "bill"},
    group="consumption",
)

MONTHLY_UNITS = Question(
    id="monthly_kwh",
    field="monthly_kwh",
    kind="number",
    prompt="How many units do you use per month?",
    spoken_prompt="How many units do you use in a month?",
    help_text="Your bill shows this as units or kWh. An average month is fine.",
    unit="kWh/month",
    min_value=1,
    depends_on={"consumption_method": "units"},
    group="consumption",
)

INSTALLATION_TYPE = Question(
    id="installation_type",
    field="installation_type",
    kind="single_choice",
    prompt="Where will the solar panels be installed?",
    spoken_prompt="Where would the panels go — on a roof, or on the ground?",
    help_text="This changes how much space each panel needs.",
    options=(
        Option("rooftop", "Rooftop", "On the roof of a building.", "home",
               ("roof", "rooftop", "on my roof", "terrace")),
        Option("ground_mounted", "Ground-mounted", "On open ground, on frames.", "layers",
               ("ground", "on the ground", "open land", "yard")),
        Option("farm_land", "Farm land", "On agricultural land.", "sprout",
               ("farm", "field", "farm land", "my land")),
        Option("parking_structure", "Parking structure", "As a canopy over parking.", "car",
               ("parking", "carport", "shed over parking")),
        Option("mixed", "A mix", "More than one of these.", "grid", ("mixed", "both")),
        Option("not_sure", "Not sure yet", "We will assume a sensible middle option.",
               "help-circle", ("not sure", "don't know", "haven't decided")),
    ),
    required=True,
    group="space",
)

AVAILABLE_AREA = Question(
    id="available_area",
    field="available_area",
    kind="area",
    prompt="How much space is available?",
    spoken_prompt="How much space do you have for the panels?",
    help_text=(
        "Enter it in whichever unit you use, give the length and width, or draw the area on "
        "the map."
    ),
    unknown_label="I don't know the area",
    unknown_effect=(
        "We will size the system to your electricity use instead, and tell you how much "
        "space it needs."
    ),
    group="space",
)

SHADING = Question(
    id="shading",
    field="shading_level",
    kind="single_choice",
    prompt="Is the area shaded at any point in the day?",
    spoken_prompt="Does anything shade that area — trees, a tank, or a nearby building?",
    help_text="Shade costs more output than most people expect, so it is worth answering.",
    options=(
        Option("none", "Nothing shades it", "Open sky all day.", "sun"),
        Option("light", "A little shade", "Something clips the edge early or late.", "cloud-sun"),
        Option("moderate", "Some shade", "Shaded for a few hours a day.", "cloud"),
        Option("heavy", "A lot of shade", "Shaded much of the day.", "cloud-rain"),
        Option("unknown", "I'm not sure", "We will assume a typical amount.", "help-circle",
               ("not sure", "don't know")),
    ),
    group="site",
)

BATTERY_WANTED = Question(
    id="wants_battery",
    field="wants_battery",
    kind="boolean",
    prompt="Do you want battery backup?",
    spoken_prompt="Do you want batteries, so you have power when the grid goes out?",
    help_text=(
        "Batteries store daytime solar for the evening and keep you running during a power "
        "cut. They add a significant amount to the cost."
    ),
    group="storage",
)

BACKUP_HOURS = Question(
    id="desired_backup_hours",
    field="desired_backup_hours",
    kind="number",
    prompt="How many hours of backup do you need?",
    spoken_prompt="How many hours should the battery keep things running?",
    help_text="Think about how long power cuts usually last where you are.",
    unit="hours",
    min_value=0.5,
    max_value=72,
    unknown_label="I don't know",
    unknown_effect="We will size the battery to cover your usual evening use.",
    depends_on={"wants_battery": True},
    group="storage",
)

CRITICAL_LOAD = Question(
    id="critical_load_kw",
    field="critical_load_kw",
    kind="number",
    prompt="What must stay on during a power cut?",
    spoken_prompt="What has to keep running when the power goes out?",
    help_text="Lights, fans and a fridge are usually enough. Air conditioning needs a much larger battery.",
    unit="kW",
    min_value=0.05,
    unknown_label="Help me estimate",
    unknown_effect="We will assume your essential load is your average draw.",
    depends_on={"wants_battery": True},
    group="storage",
)

GRID_CONNECTED = Question(
    id="grid_connected",
    field="grid_connected",
    kind="boolean",
    prompt="Do you have a grid connection?",
    spoken_prompt="Do you have electricity from the grid at this place?",
    help_text="Without a grid connection, the system has to carry the whole load itself.",
    group="storage",
)

# ---------------------------------------------------------------- existing array (§2)

PANEL_KNOWLEDGE = Question(
    id="panel_knowledge",
    field="panel_knowledge",
    kind="single_choice",
    prompt="What do you know about the panels?",
    spoken_prompt="Do you know what kind of panels they are?",
    help_text="Whatever you know is enough — we will fill in the rest and say what we assumed.",
    options=(
        Option("specs", "I know the wattage",
               "The number printed on the panel, like 550 W.", "gauge",
               ("i know the wattage", "550 watts", "i know the power")),
        Option("model", "I know the brand or model",
               "We will record it and ask you to check the wattage on the same label.",
               "receipt",
               ("i know the brand", "the model", "make and model")),
        Option("unknown", "I do not know",
               "We will use a typical modern panel and tell you which.", "help-circle",
               ("no idea", "not sure", "i do not know", "dont know")),
    ),
    group="existing",
)


PANEL_COUNT = Question(
    id="panel_count",
    field="panel_count",
    kind="number",
    prompt="How many panels do you have?",
    spoken_prompt="How many solar panels are installed?",
    help_text="Count the panels on the roof or in the array. An exact number is best.",
    unit="panels",
    min_value=1,
    max_value=1_000_000,
    required=True,
    group="existing",
)

PANEL_WATTS = Question(
    id="panel_watts",
    field="panel_watts",
    kind="single_choice",
    prompt="What is the rating of each panel?",
    spoken_prompt="How many watts is each panel?",
    help_text=(
        "Printed on a label on the back of the panel, and on your installation paperwork. "
        "It looks like 550 W or 550 Wp."
    ),
    options=tuple(
        Option(
            str(entry["watts"]),
            str(entry["label"]),
            str(entry["note"]),
            synonyms=(str(entry["watts"]), f"{entry['watts']} watts"),
        )
        for entry in _A.PANEL_WATTAGE_OPTIONS
    ),
    depends_on={"panel_knowledge": "specs"},
    unknown_label="I do not know the wattage",
    unknown_effect=(
        "We will assume a typical panel of this type and say so in your results. Your "
        "generation figure will be less precise until you enter the real rating."
    ),
    group="existing",
)

PANEL_MODEL = Question(
    id="panel_model",
    field="panel_model",
    kind="text",
    prompt="Which panel is it? (optional)",
    spoken_prompt="Do you know the make and model of the panels?",
    help_text=(
        "Manufacturer and model. We record it with your estimate for reference. We do not "
        "hold a catalogue of panel specifications, so we will also ask for the wattage — "
        "it is printed on the same label."
    ),
    depends_on={"panel_knowledge": "model"},
    group="existing",
)


#: Wattage asked again on the model branch, because knowing the brand does not tell us the
#: rating and we will not invent one from a product name.
PANEL_WATTS_WITH_MODEL = Question(
    id="panel_watts_model",
    field="panel_watts",
    kind="single_choice",
    prompt="And what power is written on it?",
    spoken_prompt="What wattage does the label say?",
    help_text="On the same label as the model name, shown as W or Wp.",
    options=PANEL_WATTS.options,
    depends_on={"panel_knowledge": "model"},
    unknown_label="It is not legible",
    unknown_effect="We will assume a typical panel of this type and label it as assumed.",
    group="existing",
)

PANEL_COUNT_NEW = Question(
    id="panel_count_new",
    field="panel_count",
    kind="number",
    prompt="How many panels do you want? (optional)",
    spoken_prompt="Do you have a number of panels in mind?",
    help_text=(
        "Leave this blank and we will recommend a number based on your electricity use "
        "and your space. You can change it afterwards and everything recalculates."
    ),
    unit="panels",
    min_value=1,
    max_value=1_000_000,
    unknown_label="Recommend a number for me",
    unknown_effect=(
        "We will work out the system size from your consumption and space, then show how "
        "many panels that is."
    ),
    group="equipment",
)


# ------------------------------------------------------- what each persona is powering

FARM_LOADS = Question(
    id="farm_loads",
    field="farm_loads",
    kind="multi_choice",
    prompt="What are you powering?",
    spoken_prompt="What on the farm do you want to run on solar?",
    help_text="Pick everything that applies. It tells us when your power is actually used.",
    options=(
        Option("water_pump", "Water pump", "Borewell or surface pump.", "droplet",
               ("pump", "borewell", "motor")),
        Option("irrigation", "Irrigation system", "Drip, sprinkler or channel systems.", "sprout",
               ("irrigation", "drip", "sprinkler")),
        Option("farm_building", "Farm building", "Sheds, lighting, fans, workshop.", "home",
               ("shed", "building", "lights")),
        Option("cold_storage", "Cold storage", "Chilling or cold room for produce.", "cloud",
               ("cold storage", "chiller", "cold room")),
        Option("machinery", "Agricultural machinery", "Threshers, chaff cutters, mills.", "factory",
               ("machinery", "thresher", "mill")),
        Option("multiple", "Several of these", "A mix of loads across the farm.", "grid",
               ("everything", "all of it", "multiple")),
    ),
    group="loads",
)

BUSINESS_TYPE = Question(
    id="business_type",
    field="business_type",
    kind="single_choice",
    prompt="What kind of business is it?",
    spoken_prompt="What sort of business do you run?",
    help_text="Different trades use power at very different times of day.",
    options=(
        Option("retail", "Shop or retail", "Goods sold over a counter.", "store"),
        Option("food", "Restaurant or food", "Cooking, refrigeration, long hours.", "store"),
        Option("office", "Office", "Computers, lighting, air conditioning.", "grid"),
        Option("clinic", "Clinic or pharmacy", "Refrigeration and equipment, often with backup.", "school"),
        Option("workshop", "Workshop or service", "Tools, compressors, welding.", "factory"),
        Option("other", "Something else", "We will use a general small-business pattern.", "help-circle"),
    ),
    group="loads",
)

FACILITY_TYPE = Question(
    id="facility_type",
    field="facility_type",
    kind="single_choice",
    prompt="What kind of facility is it?",
    spoken_prompt="What sort of facility is this?",
    help_text="This decides which technical questions are worth asking you.",
    options=(
        Option("office", "Office building", "Desks, lighting, air conditioning.", "grid"),
        Option("factory", "Factory or manufacturing", "Process machinery and motors.", "factory"),
        Option("warehouse", "Warehouse or logistics", "Large roof, lighting, some handling plant.", "layers"),
        Option("retail", "Retail or mall", "Long trading hours, heavy cooling.", "store"),
        Option("hospitality", "Hotel or hospitality", "Round-the-clock demand.", "home"),
        Option("other", "Something else", "We will use a general commercial pattern.", "help-circle"),
    ),
    group="loads",
)

INSTITUTION_TYPE = Question(
    id="institution_type",
    field="facility_type",
    kind="single_choice",
    prompt="What kind of institution is it?",
    spoken_prompt="Is this a school, a hospital, or something else?",
    help_text="A school empties in the afternoon; a hospital never does.",
    options=(
        Option("school", "School", "Daytime use, long holidays.", "school"),
        Option("college", "College or university", "Daytime use, labs and hostels.", "school"),
        Option("hospital", "Hospital or health centre", "Continuous demand, critical backup.", "school"),
        Option("government", "Government or public office", "Standard working hours.", "grid"),
        Option("religious", "Place of worship", "Concentrated use at particular times.", "home"),
        Option("other", "Something else", "We will use a general institutional pattern.", "help-circle"),
    ),
    group="loads",
)

# --------------------------------------------------------- commercial and industrial

PEAK_DEMAND = Question(
    id="peak_demand_kw",
    field="peak_demand_kw",
    kind="number",
    prompt="What is your peak demand?",
    spoken_prompt="Do you know your maximum demand in kilowatts?",
    help_text=(
        "Shown on a commercial bill as maximum demand or sanctioned load, usually in kW or "
        "kVA. Solar rarely reduces it much, because peaks often fall outside daylight."
    ),
    unit="kW",
    min_value=0.5,
    max_value=1_000_000,
    unknown_label="I do not know",
    unknown_effect="We will leave demand charges out of the savings rather than guess at them.",
    group="operations",
)

CONNECTED_LOAD = Question(
    id="connected_load_kw",
    field="connected_load_kw",
    kind="number",
    prompt="What is your connected load?",
    spoken_prompt="What is the total connected load of the plant?",
    help_text="The total rating of everything that could run at once, from your connection agreement.",
    unit="kW",
    min_value=0.5,
    max_value=1_000_000,
    unknown_label="I do not know",
    unknown_effect="We will size from your consumption instead, which is the better guide anyway.",
    group="operations",
)

OFFSET_TARGET = Question(
    id="offset_target",
    field="offset_target_pct",
    kind="single_choice",
    prompt="How much of your electricity do you want solar to cover?",
    spoken_prompt="What share of your power should solar cover?",
    help_text=(
        "Covering everything is not always the best value — the last share is the hardest "
        "to use on site and usually gets exported cheaply."
    ),
    options=(
        Option("30", "About a third", "A cautious first step.", "zap"),
        Option("50", "About half", "A common, comfortable target.", "zap"),
        Option("75", "Most of it", "Ambitious but usually still self-consumed.", "zap"),
        Option("100", "All of it", "Matches your annual consumption.", "sun"),
    ),
    unknown_label="Recommend a target",
    unknown_effect="We will size to cover your consumption and show what share you actually use.",
    group="operations",
)

GRID_CONNECTION = Question(
    id="grid_connection",
    field="grid_connection",
    kind="single_choice",
    prompt="How is the site connected to the grid?",
    spoken_prompt="Are you connected to the grid, and can you export?",
    help_text="Whether you can export surplus decides how much a larger system is worth.",
    options=(
        Option("net_metering", "Grid connected, can export",
               "Surplus goes back and is credited.", "grid"),
        Option("no_export", "Grid connected, no export",
               "Surplus is wasted unless stored or used.", "grid"),
        Option("off_grid", "Not connected", "The system carries the whole load.", "battery"),
    ),
    unknown_label="I am not sure",
    unknown_effect="We will assume a normal grid connection that credits exported units.",
    group="storage",
)

INVERTER_CAPACITY = Question(
    id="inverter_capacity",
    field="inverter_ac_capacity_kw",
    kind="number",
    prompt="What size is your inverter?",
    spoken_prompt="How many kilowatts is the inverter?",
    help_text="AC rating, from the inverter label or your quote.",
    unit="kW",
    min_value=0.5,
    max_value=1_000_000,
    unknown_label="I do not know",
    unknown_effect=(
        "We will size the inverter from the array at a standard 1.2 ratio, which is what "
        "most installations use."
    ),
    group="equipment",
)


# ---------------------------------------------------------------- persona specifics

PUMP_LIST = Question(
    id="pumps",
    field="pumps",
    kind="pump_list",
    prompt="Tell us about your pumps",
    spoken_prompt="What pumps do you run, and for how long each day?",
    help_text="The horsepower is usually written on the motor's nameplate.",
    depends_on={"consumption_method": "equipment"},
    group="consumption",
)

EQUIPMENT_LIST = Question(
    id="equipment",
    field="equipment",
    kind="equipment_list",
    prompt="What else do you run?",
    spoken_prompt="What else uses electricity — lights, fans, a fridge?",
    help_text="Add what you use most. Rough hours are fine.",
    depends_on={"consumption_method": "equipment"},
    group="consumption",
)

PUMP_DETAIL = Question(
    id="pump_horsepower",
    field="pump_horsepower",
    kind="number",
    prompt="What size is your main pump?",
    spoken_prompt="How many horsepower is your pump?",
    help_text="Written on the motor's nameplate, usually as HP.",
    unit="HP",
    min_value=0.5,
    max_value=200,
    unknown_label="I don't know",
    unknown_effect="We will skip the pumping figures and show energy only.",
    group="farm",
)

PUMP_HEAD = Question(
    id="pump_head_metres",
    field="pump_head_metres",
    kind="number",
    prompt="How deep is the water?",
    spoken_prompt="How deep is your borewell, or how high does the water have to be lifted?",
    help_text="The depth from the water level to where it comes out.",
    unit="metres",
    min_value=1,
    max_value=500,
    unknown_label="I don't know",
    unknown_effect="We will show pump running hours but not how much water that moves.",
    group="farm",
)

FLOOR_AREA = Question(
    id="floor_area",
    field="floor_area_m2",
    kind="number",
    prompt="How large is the building?",
    spoken_prompt="How big is the building, in square feet or square metres?",
    help_text="A rough figure is fine.",
    unit="m²",
    min_value=5,
    depends_on={"consumption_method": "floor_area"},
    group="consumption",
)

OPERATING_HOURS = Question(
    id="operating_hours",
    field="operating_hours",
    kind="number",
    prompt="How many hours a day do you operate?",
    spoken_prompt="How many hours a day does the place run?",
    help_text="This tells us how much of your use overlaps with daylight.",
    unit="hours/day",
    min_value=1,
    max_value=24,
    unknown_label="I don't know",
    unknown_effect="We will assume a typical pattern for this kind of place.",
    group="operations",
)

BUDGET = Question(
    id="budget",
    field="budget",
    kind="currency",
    prompt="Do you have a budget in mind?",
    spoken_prompt="Is there a budget you want to stay within?",
    help_text="Optional. If you give one, we will not recommend a system beyond it.",
    unknown_label="No fixed budget",
    unknown_effect="We will size the system to your electricity use and your space.",
    group="money",
)

TARIFF = Question(
    id="tariff",
    field="tariff_per_kwh",
    kind="currency",
    prompt="What do you pay per unit of electricity?",
    spoken_prompt="How much do you pay for one unit of electricity?",
    help_text="Shown on your bill as the rate per unit or per kWh.",
    unknown_label="I don't know my rate",
    unknown_effect=(
        "We will use a typical rate for your area, and show you which one we used so you "
        "can correct it."
    ),
    group="money",
)

# ---------------------------------------------------------------- detailed extras (§15)

PANEL_TECHNOLOGY = Question(
    id="panel_technology",
    field="panel_key",
    kind="single_choice",
    prompt="Which panel technology?",
    help_text="If you have a quote, match it here. Otherwise the default is current mainstream equipment.",
    unknown_label="Use the recommended panel",
    unknown_effect="We will assume a modern high-efficiency panel and say so in the assumptions.",
    group="equipment",
)

TILT = Question(
    id="tilt",
    field="tilt_deg",
    kind="number",
    prompt="What tilt will the panels sit at?",
    help_text="0° is flat, 90° is vertical.",
    unit="°",
    min_value=0,
    max_value=90,
    unknown_label="Use the best angle for my location",
    unknown_effect=(
        "We will test a range of angles against your location's own weather and use the "
        "one that collects the most energy."
    ),
    group="equipment",
)

AZIMUTH = Question(
    id="azimuth",
    field="azimuth_deg",
    kind="number",
    prompt="Which direction will the panels face?",
    help_text="180° is due south, 0° is due north.",
    unit="°",
    min_value=0,
    max_value=359,
    unknown_label="Use the best direction for my location",
    unknown_effect="We will pick the direction that collects the most energy where you are.",
    group="equipment",
)

INVERTER_EFFICIENCY = Question(
    id="inverter_efficiency",
    field="inverter_efficiency",
    kind="number",
    prompt="Inverter efficiency",
    help_text="From the inverter datasheet, as a percentage.",
    unit="%",
    min_value=80,
    max_value=100,
    unknown_label="Use a typical value",
    unknown_effect="We will assume 96%, which is normal for current inverters.",
    group="equipment",
)

DC_AC_RATIO = Question(
    id="dc_ac_ratio",
    field="dc_ac_ratio",
    kind="number",
    prompt="DC to AC ratio",
    help_text=(
        "Panel capacity divided by inverter capacity. Above about 1.3 the inverter starts "
        "clipping the midday peak."
    ),
    min_value=0.8,
    max_value=2.0,
    unknown_label="Use a standard ratio",
    unknown_effect="We will assume 1.2, a common choice.",
    group="equipment",
)

SYSTEM_COST = Question(
    id="system_cost",
    field="system_cost_override",
    kind="currency",
    prompt="What will the system cost?",
    help_text="If you have a quote, enter it. This makes the payback figure real rather than indicative.",
    unknown_label="I don't have a quote yet",
    unknown_effect=(
        "We will use a typical installed cost for a system this size, clearly marked as an "
        "estimate rather than a quote."
    ),
    group="money",
)


# ------------------------------------------------------------- expert datasheet (§14)

def _datasheet_question(entry: dict[str, Any]) -> Question:
    return Question(
        id=f"panel_{entry['key']}",
        field=f"panel_{entry['key']}",
        kind="number",
        prompt=str(entry["label"]),
        help_text=str(entry["note"]),
        unit=str(entry["unit"]),
        min_value=0.1,
        max_value=2000,
        unknown_label="Not on hand",
        unknown_effect=(
            "Left blank. It is recorded for your reference when supplied and does not "
            "change the energy figures, which are driven by rated power, efficiency and "
            "the temperature coefficient."
        ),
        group="datasheet",
    )


DATASHEET_QUESTIONS: tuple[Question, ...] = tuple(
    _datasheet_question(entry) for entry in _A.DATASHEET_FIELDS
)

PANEL_LENGTH = Question(
    id="panel_length",
    field="panel_length_m",
    kind="number",
    prompt="Panel length",
    help_text="From the datasheet, in metres.",
    unit="m",
    min_value=0.2,
    max_value=5,
    unknown_label="Work it out for me",
    unknown_effect="We will derive the panel area from its wattage and efficiency.",
    group="datasheet",
)

PANEL_WIDTH = Question(
    id="panel_width",
    field="panel_width_m",
    kind="number",
    prompt="Panel width",
    help_text="From the datasheet, in metres.",
    unit="m",
    min_value=0.2,
    max_value=5,
    unknown_label="Work it out for me",
    unknown_effect="We will derive the panel area from its wattage and efficiency.",
    group="datasheet",
)


# --------------------------------------------------------------------------------------
# Flows (§8)
# --------------------------------------------------------------------------------------

#: The question that establishes what a persona is actually running. §7 forbids one
#: universal questionnaire, and this is where that starts: a farmer is asked about pumps
#: and cold storage, a shopkeeper about their trade, a factory about its process.
LOADS_QUESTION: dict[str, Question] = {
    "farm": FARM_LOADS,
    "shop": BUSINESS_TYPE,
    "commercial": FACILITY_TYPE,
    "institution": INSTITUTION_TYPE,
}


def _loads_step(user_type: str) -> Step | None:
    """What this persona is powering. Absent for home and exploring, who have no sub-type."""
    question = LOADS_QUESTION.get(user_type)
    if question is None:
        return None
    return Step(
        id="loads",
        title="What you are powering",
        subtitle="So the questions after this are the ones worth asking you.",
        questions=(question,),
    )


def _consumption_step(user_type: str) -> Step:
    questions: list[Question] = [CONSUMPTION_METHOD, MONTHLY_BILL, MONTHLY_UNITS]
    if user_type == "farm":
        questions += [PUMP_LIST, EQUIPMENT_LIST]
    elif user_type in {"commercial", "institution"}:
        questions += [FLOOR_AREA, EQUIPMENT_LIST]
    else:
        questions += [EQUIPMENT_LIST]
    return Step(
        id="consumption",
        title="Your electricity use",
        subtitle="This is what we size the system against.",
        questions=tuple(questions),
    )


def _operations_step(user_type: str, mode: str) -> Step | None:
    """How the site runs. Only asked where it changes the answer.

    A homeowner has nothing useful to say about connected load or peak demand, and asking
    would be the universal questionnaire §7 rules out. A factory has a great deal to say,
    and in detailed mode is asked all of it.
    """
    questions: list[Question] = []

    if user_type in {"shop", "commercial", "institution"}:
        questions.append(OPERATING_HOURS)

    if user_type in {"commercial", "institution"}:
        questions.append(OFFSET_TARGET)
        questions.append(GRID_CONNECTION)

    if user_type == "commercial" and mode == "detailed":
        # The industrial inputs. Peak demand and connected load only mean something to
        # somebody who has a commercial connection agreement in front of them.
        questions.extend([PEAK_DEMAND, CONNECTED_LOAD])

    if not questions:
        return None

    return Step(
        id="operations",
        title="How you operate",
        subtitle="When you use power decides how much of the solar you actually use.",
        questions=tuple(questions),
    )


def flow_for(user_type: str, mode: str = "quick", goal: str = "install") -> list[Step]:
    """The ordered interview for this user, this mode, and what they came to do.

    The goal reorders the interview rather than merely adding to it. Somebody who already
    owns an array is asked what it is, early, because that measurement determines the
    result. Somebody planning one is not asked about panels at all until their consumption
    and space are known — the number of panels is the answer they came for, and asking it
    first would be asking them to do the sizing themselves (§3).
    """
    steps: list[Step] = [
        Step(
            id="location",
            title="Your location",
            subtitle="Used to look up real sunlight and weather data for your area.",
            questions=(LOCATION,),
        ),
    ]

    if goal == "existing":
        # The array is the subject of the whole estimate, so it is established first.
        steps.append(
            Step(
                id="existing",
                title="Your existing system",
                subtitle="These two answers tell us the capacity you already have installed.",
                questions=(
                    PANEL_COUNT, PANEL_KNOWLEDGE, PANEL_WATTS, PANEL_MODEL,
                    PANEL_WATTS_WITH_MODEL, INVERTER_CAPACITY,
                ),
            )
        )

    loads = _loads_step(user_type)
    if loads is not None:
        steps.append(loads)

    steps.append(_consumption_step(user_type))

    if goal != "existing":
        # Space constrains what can be installed. For an existing array it is already
        # occupied, so asking would be asking about a decision already taken.
        steps.append(
            Step(
                id="space",
                title="Where the panels go",
                subtitle="How much you can install depends on the space available.",
                questions=(INSTALLATION_TYPE, AVAILABLE_AREA, SHADING),
            )
        )
    else:
        steps.append(
            Step(
                id="site",
                title="Your site",
                subtitle="A couple of things that affect how much your array actually produces.",
                questions=(INSTALLATION_TYPE, SHADING),
            )
        )

    if user_type == "farm":
        steps.append(
            Step(
                id="farm",
                title="Your pump",
                subtitle="So we can tell you what the system runs, not just how many units it makes.",
                questions=(PUMP_DETAIL, PUMP_HEAD),
            )
        )

    operations = _operations_step(user_type, mode)
    if operations is not None:
        steps.append(operations)

    steps.append(
        Step(
            id="storage",
            title="Battery backup",
            subtitle="Only if you need power when the grid is down, or after dark.",
            questions=(BATTERY_WANTED, BACKUP_HOURS, CRITICAL_LOAD, GRID_CONNECTED),
        )
    )

    if mode == "detailed":
        steps.append(
            Step(
                id="equipment",
                title="Equipment and orientation",
                subtitle="Leave anything you do not know — we will use a stated default.",
                questions=(
                    PANEL_TECHNOLOGY, PANEL_WATTS, PANEL_COUNT_NEW, TILT, AZIMUTH,
                    INVERTER_CAPACITY, INVERTER_EFFICIENCY, DC_AC_RATIO,
                ),
            )
        )
        steps.append(
            Step(
                id="datasheet",
                title="Panel datasheet",
                subtitle=(
                    "Optional. Only the rated power, efficiency and temperature coefficient "
                    "change the energy figures — the rest is recorded for your reference."
                ),
                questions=(PANEL_LENGTH, PANEL_WIDTH, *DATASHEET_QUESTIONS),
            )
        )
        steps.append(
            Step(
                id="money",
                title="Costs and tariff",
                subtitle="Needed for payback and savings. All editable afterwards.",
                questions=(TARIFF, SYSTEM_COST, BUDGET),
            )
        )

    else:
        steps.append(
            Step(
                id="money",
                title="One last thing",
                subtitle="Optional — it makes the savings figure yours rather than typical.",
                questions=(TARIFF,),
            )
        )

    return steps


def catalogue() -> dict[str, Any]:
    """Everything the frontend needs to render any interview, in one payload."""
    from app.estimate import assumptions as A
    from app.estimate.demand import APPLIANCES

    return {
        "user_types": [u.to_dict() for u in USER_TYPES],
        "goals": [g.to_dict() for g in GOALS],
        "modes": list(MODES),
        # Keyed user type -> mode -> goal. Enumerated rather than computed on demand so the
        # client can render any branch without another round trip, and so a flow that fails
        # to build fails here rather than in front of a user.
        "flows": {
            user.key: {
                mode["key"]: {
                    goal.key: [s.to_dict() for s in flow_for(user.key, mode["key"], goal.key)]
                    for goal in GOALS
                }
                for mode in MODES
            }
            for user in USER_TYPES
        },
        "appliances": [
            {
                "key": a.key,
                "label": a.label,
                "category": a.category,
                "typical_watts": a.typical_watts,
                "default_hours_per_day": a.default_hours_per_day,
                "default_days_per_month": a.default_days_per_month,
                "user_types": list(a.user_types),
                "hint": a.plain_hint,
            }
            for a in APPLIANCES.values()
        ],
        "panel_wattages": [dict(entry) for entry in _A.PANEL_WATTAGE_OPTIONS],
        "datasheet_fields": [dict(entry) for entry in _A.DATASHEET_FIELDS],
        "default_panel_watts": _A.DEFAULT_PANEL_WATTS,
        "panel_technologies": [
            {
                "key": p.key,
                "display_name": p.display_name,
                "plain_name": p.plain_name,
                "efficiency_pct": round(p.efficiency * 100, 1),
                "degradation_pct_per_year": round(p.degradation_rate_per_year * 100, 2),
                "note": p.note,
            }
            for p in A.PANEL_TECHNOLOGIES.values()
        ],
        "installation_types": [
            {"key": k, "label": v["label"], "note": v["note"]}
            for k, v in A.AREA_FACTORS.items()
        ],
        "shading_levels": [
            {"key": k, **v} for k, v in A.SHADING_LEVELS.items()
        ],
        "loss_stack": [
            {
                "key": item.key,
                "label": item.label,
                "default_pct": round(item.fraction * 100, 2),
                "explanation": item.plain_explanation,
            }
            for item in A.DEFAULT_LOSS_STACK
        ],
    }
