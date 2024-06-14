import spacy
from spacy import displacy


nlp_ner = spacy.load("A:/parsing/NLP_Resume_Parser/model-best")

doc = nlp_ner('''I have several years of experience with NLP and MLOps. I already implemented Ticket Classification algorithms with BERT, Named Entity Recognition algorithms with spaCy as well as Topic Modeling and Text Clustering methods. Moreover I have worked with AWS, Kubernetes and Docker.''')
displacy.render(doc, style="ent", jupyter=True)
