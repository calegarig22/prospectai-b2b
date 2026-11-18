-- 0002 — guarda o TEXTO do nicho como foi escrito (com os comentários).
--
-- O motor usa a versão validada em JSON (orgs.nicho). Mas quem edita é uma
-- pessoa, e os comentários (# ...) explicam cada campo: regerar o texto a partir
-- do JSON apagava todos eles a cada "Salvar".
ALTER TABLE orgs ADD COLUMN nicho_yaml TEXT;
