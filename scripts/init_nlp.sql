-- FAQ knowledge (small talk / meta)
CREATE TABLE IF NOT EXISTS faqs (
  faq_id     INTEGER PRIMARY KEY,
  tag        TEXT,            -- e.g., 'who_made_you', 'how_are_you'
  question   TEXT NOT NULL,   -- canonical question
  answer     TEXT NOT NULL    -- final answer to show
);

-- Training phrases for intents (light supervision)
CREATE TABLE IF NOT EXISTS intent_phrases (
  phrase_id   INTEGER PRIMARY KEY,
  intent_name TEXT NOT NULL,  -- e.g., 'greet','ask_categories','capabilities','bot_identity'
  phrase      TEXT NOT NULL   -- example user utterance
);

-- FAQs
INSERT INTO faqs (tag,question,answer) VALUES
('who_made_you','who created you','I was built by RealtyNexus to help you find properties and explore investment plans in Sri Lanka.'),
('how_are_you','how are you','I’m great—ready to search properties for you! 😊'),
('what_are_you','what are you','I’m RealtyAI, a virtual agent that can search listings by city/type/budget and show curated investments.'),
('capabilities','what can you do','I can search by city (Colombo, Galle, Kandy), property type (apartment/house/land), bedrooms, and budget; and show current investment plans.'),
('thanks','thank you','Happy to help! Anything else you want to search?'),
('greetings','hello','Hi! Tell me city, property type, and budget (e.g., “3BR apartments in Galle under 80M”).');

-- Intent phrases
INSERT INTO intent_phrases (intent_name, phrase) VALUES
('greet','hi'), ('greet','hello'), ('greet','hey'),
('ask_categories','what property types do you have'), ('ask_categories','what types do you support'),
('capabilities','what can you do'), ('capabilities','how do you work'), ('capabilities','what are your features'),
('bot_identity','what are you'), ('bot_identity','who are you'),
('bot_creator','who made you'), ('bot_creator','who created you'),
('reset','reset'), ('reset','start over'), ('reset','clear filters'),
('nearest_query','nearest apartments to borella'), ('nearest_query','show listings near me'),
('investment_advice','what investments do you have'), ('investment_advice','show investments'), ('investment_advice','investment plans');
