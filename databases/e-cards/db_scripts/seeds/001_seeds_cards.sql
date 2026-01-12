
INSERT INTO tbl_collections (collectionSetName, totalCardsInCollection) VALUES
('Base Set', 102),
('Jungle', 64),
('Fossil', 62);


INSERT INTO tbl_types (typeName) VALUES
('Fire'),
('Water'),
('Grass'),
('Electric'),
('Psychic'),
('Fighting'),
('Dark'),
('Steel'),
('Dragon'),
('Fairy'),
('Colorless');


INSERT INTO tbl_stages (stageName) VALUES
('Basic'),
('Stage 1'),
('Stage 2');


INSERT INTO tbl_cards (
    hp, name, info, attack, damage, weak, resis, retreat, cardNumberInCollection, collection_id, type_id, stage_id
) VALUES
(60, 'Charmander', 'Lizard Pokémon', 'Scratch', '10', 'Water', NULL, '1', 46, 1, 1, 1),
(120, 'Charizard', 'Flame Pokémon', 'Fire Spin', '100', 'Water', NULL, '3', 4, 1, 1, 3),
(50, 'Bulbasaur', 'Seed Pokémon', 'Vine Whip', '10', 'Fire', NULL, '1', 44, 1, 3, 1),
(90, 'Pikachu', 'Mouse Pokémon', 'Thunder Shock', '30', 'Fighting', NULL, '1', 58, 1, 4, 1),
(100, 'Raichu', 'Mouse Pokémon', 'Thunder', '60', 'Fighting', NULL, '2', 14, 1, 4, 2),
(60, 'Squirtle', 'Tiny Turtle Pokémon', 'Bubble', '10', 'Electric', NULL, '1', 63, 1, 2, 1),
(100, 'Blastoise', 'Shellfish Pokémon', 'Hydro Pump', '40+', 'Electric', NULL, '3', 2, 1, 2, 3);
