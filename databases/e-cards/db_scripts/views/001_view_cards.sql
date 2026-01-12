CREATE VIEW vw_cards_detalhadas AS
SELECT 
    c.id AS card_id,
    c.name AS card_name,
    c.hp,
    c.info,
    c.attack,
    c.damage,
    c.weak,
    c.resis,
    c.retreat,
    c.cardNumberInCollection,
    col.collectionSetName AS collection_name,
    col.totalCardsInCollection,
    t.typeName AS type_name,
    s.stageName AS stage_name
FROM tbl_cards c
INNER JOIN tbl_collections col ON c.collection_id = col.id
INNER JOIN tbl_types t ON c.type_id = t.id
INNER JOIN tbl_stages s ON c.stage_id = s.id;
