
DROP VIEW IF EXISTS vw_cards_detalhadas;

CREATE VIEW vw_cards_detalhadas AS
SELECT 
    -- Campos da tabela tbl_cards
    c.id AS id_carta,
    c.name AS nome_carta,
    c.hp AS pontos_hp,
    c.info AS informacoes,
    c.attack AS ataque,
    c.damage AS dano,
    c.weak AS fraqueza,
    c.resis AS resistencia,
    c.retreat AS recuo,
    c.cardNumberInCollection AS numero_na_colecao,
    
    -- Campos da tabela tbl_collections
    col.id AS id_colecao,
    col.collectionSetName AS nome_colecao,
    col.totalCardsInCollection AS total_cartas_colecao,
    
    -- Campos da tabela tbl_types
    t.id AS id_tipo,
    t.typeName AS nome_tipo,
    
    -- Campos da tabela tbl_stages
    s.id AS id_fase,
    s.stageName AS nome_fase
FROM tbl_cards AS c
INNER JOIN tbl_collections AS col ON c.collection_id = col.id
INNER JOIN tbl_types AS t ON c.type_id = t.id
INNER JOIN tbl_stages AS s ON c.stage_id = s.id;
