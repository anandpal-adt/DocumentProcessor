import spacy

text = ''' ...(not shown)... '''

# Print entity labels and text for the untrained model:
nlp = spacy.load('en_core_web_sm')
doc = nlp(text)
print("\nEntities found before training:")
for ent in doc.ents:
    if ent.label_=='ORG':
        print(ent.label_, ent.text)

# Load the trained model:
nlp = spacy.load('/tmp/model')
doc = nlp(text)

# Print entity labels and text
print("\\nEntities found after training:")
for ent in doc.ents:
    if ent.label_=='ORG':
        print(ent.label_, ent.text)