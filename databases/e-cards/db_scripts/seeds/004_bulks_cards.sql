
INSERT INTO tbl_cards (
    hp, name, info, attack, damage, weak, resis, retreat, cardNumberInCollection, collection_id, type_id, stage_id
) VALUES
-- Base Set
(40, 'Sandshrew', 'Mouse Pokémon', 'Scratch', '10', 'Grass', NULL, '1', 62, 1, 6, 1),
(70, 'Sandslash', 'Mouse Pokémon', 'Slash', '20', 'Grass', NULL, '1', 35, 1, 6, 2),
(50, 'Poliwag', 'Tadpole Pokémon', 'Water Gun', '10+', 'Electric', NULL, '1', 59, 1, 2, 1),
(80, 'Poliwhirl', 'Tadpole Pokémon', 'Amnesia', '—', 'Electric', NULL, '2', 40, 1, 2, 2),
(100, 'Poliwrath', 'Tadpole Pokémon', 'Water Gun', '30+', 'Electric', NULL, '3', 13, 1, 2, 3),
(40, 'Magnemite', 'Magnet Pokémon', 'Thunder Wave', '10', 'Fighting', NULL, '1', 56, 1, 4, 1),
(80, 'Magneton', 'Magnet Pokémon', 'Selfdestruct', '80', 'Fighting', NULL, '2', 9, 1, 4, 2),
(50, 'Voltorb', 'Ball Pokémon', 'Tackle', '10', 'Fighting', NULL, '1', 67, 1, 4, 1),
(60, 'Electrode', 'Ball Pokémon', 'Electric Shock', '30', 'Fighting', NULL, '1', 21, 1, 4, 2),
(40, 'Koffing', 'Poison Gas Pokémon', 'Smog', '10', 'Psychic', NULL, '1', 58, 1, 6, 1),

-- Jungle
(50, 'Bellsprout', 'Flower Pokémon', 'Vine Whip', '10', 'Fire', NULL, '1', 49, 2, 3, 1),
(70, 'Weepinbell', 'Flower Pokémon', 'Poisonpowder', '20', 'Fire', NULL, '1', 42, 2, 3, 2),
(90, 'Victreebel', 'Flycatcher Pokémon', 'Lure', '—', 'Fire', NULL, '2', 14, 2, 3, 3),
(60, 'Doduo', 'Twin Bird Pokémon', 'Fury Attack', '10x', 'Electric', NULL, '1', 48, 2, 11, 1),
(80, 'Dodrio', 'Triple Bird Pokémon', 'Rage', '10+', 'Electric', NULL, '1', 34, 2, 11, 2),
(50, 'Exeggcute', 'Egg Pokémon', 'Hypnosis', '—', 'Fire', NULL, '1', 52, 2, 3, 1),
(80, 'Exeggutor', 'Coconut Pokémon', 'Teleport', '—', 'Fire', NULL, '2', 35, 2, 3, 2),
(70, 'Tauros', 'Wild Bull Pokémon', 'Stomp', '20+', 'Fighting', NULL, '2', 47, 2, 11, 1),
(60, 'Kangaskhan', 'Parent Pokémon', 'Comet Punch', '20x', 'Fighting', NULL, '2', 5, 2, 11, 1),
(70, 'Pinsir', 'Stag Beetle Pokémon', 'Guillotine', '50', 'Fire', NULL, '2', 24, 2, 3, 1),

-- Fossil
(40, 'Grimer', 'Sludge Pokémon', 'Poison Gas', '10', 'Psychic', NULL, '1', 61, 3, 6, 1),
(80, 'Muk', 'Sludge Pokémon', 'Sludge', '30', 'Psychic', NULL, '2', 13, 3, 6, 2),
(50, 'Horsea', 'Dragon Pokémon', 'Smokescreen', '10', 'Electric', NULL, '1', 52, 3, 2, 1),
(80, 'Seadra', 'Dragon Pokémon', 'Water Gun', '20+', 'Electric', NULL, '2', 42, 3, 2, 2),
(90, 'Kingler', 'Pincer Pokémon', 'Crabhammer', '40', 'Electric', NULL, '2', 34, 3, 2, 2),
(70, 'Lapras', 'Transport Pokémon', 'Water Gun', '10+', 'Electric', NULL, '2', 10, 3, 2, 1),
(60, 'Slowpoke', 'Dopey Pokémon', 'Spacing Out', '—', 'Electric', NULL, '1', 55, 3, 2, 1),
(80, 'Slowbro', 'Hermit Crab Pokémon', 'Amnesia', '—', 'Electric', NULL, '2', 32, 3, 2, 2),
(100, 'Articuno', 'Freeze Pokémon', 'Blizzard', '50', 'Electric', NULL, '2', 2, 3, 2, 1),
(100, 'Zapdos', 'Electric Pokémon', 'Thunderstorm', '40', 'Fighting', NULL, '2', 15, 3, 4, 1);
