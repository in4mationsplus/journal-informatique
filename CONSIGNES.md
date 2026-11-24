# Rédaction du journal du jour

Tu prépares le journal audio quotidien d'un informaticien, écouté en voiture
pendant son trajet de 15 minutes. Il sera lu par une synthèse vocale :
écris uniquement du texte à dire à voix haute.

## Entrée

`travail/articles.json`, écrit ce matin par GitHub Actions :
- `date_texte` : la date à annoncer ;
- `edition` : `matin` ou `midi` ;
- `mots_vises` : la longueur totale visée — un **maximum** : à midi, s'il y
  a peu de vraies nouveautés, fais plus court plutôt que de délayer ;
- `rubriques` : les rubriques autorisées, dans l'ordre d'écoute ;
- `sujets_deja_racontes` : les sujets des jours précédents ;
- `articles` : `id`, `source`, `titre`, `resume`, `lien`.

Si le fichier n'existe pas, ou si `travail/redaction.json` existe déjà,
arrête-toi sans rien modifier.

## Travail

1. Regroupe les articles qui racontent la même news, même si les titres
   diffèrent ou si l'un est en anglais : un seul sujet par news, qui cite
   les `id` de tous ses articles.
2. Écarte ce qui n'est pas de l'informatique professionnelle : tests de
   produits, bons plans, promotions, smartphones et matériel grand public,
   jeux vidéo, sciences sans lien avec l'informatique.
3. Écarte les sujets de `sujets_deja_racontes`, sauf s'il y a un vrai fait
   nouveau : dans ce cas, ne raconte que la nouveauté.
4. Range chaque sujet dans une des `rubriques`, orthographiée exactement.
5. Choisis les sujets les plus importants pour tenir en `mots_vises` mots
   environ, introduction et conclusion comprises (sans le dépasser de plus de 10 %). Un sujet
   repris par plusieurs sources est en général plus important. Une alerte
   de sécurité critique (faille exploitée, correctif urgent) passe toujours.
6. Pour chaque sujet, un texte de 80 à 200 mots, en français, clair et
   factuel : ce qui s'est passé, pourquoi ça compte pour un informaticien.
   Pas d'URL, pas de numéro de CVE sauf s'il est célèbre, pas de liste à
   puces ni de Markdown, pas de sigle obscur sans l'expliquer une fois.
   N'invente rien qui ne soit pas dans les articles.
7. Introduction : une ou deux phrases avec la date, l'édition (matin ou
   midi) et les grands titres.
   Conclusion : une phrase. N'annonce pas les rubriques : le programme
   ajoute lui-même « Rubrique sécurité. », etc.

## Sortie

Écris `travail/redaction.json` (UTF-8) :

```json
{
  "introduction": "…",
  "sujets": [
    {"titre": "…", "rubrique": "Sécurité", "articles": [3, 17], "texte": "…"}
  ],
  "conclusion": "…"
}
```

Vérifie-le avec
`python -c "import json; json.load(open('travail/redaction.json', encoding='utf-8'))"`
et compte les mots. Puis commite ce seul fichier (`git add travail/redaction.json`)
avec le message « Rédaction du jour » et pousse sur `main`. Ne modifie
aucun autre fichier.
