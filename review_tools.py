import base64
import nltk
import re

from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

regex_base64 = \
 re.compile(r'^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$')
def isBase64(s):
    if re.match(regex_base64, s.replace('\n', '')):
        return True
    return False

def extract_review(email):
    
    payload = email.get_payload()
    if not isinstance(payload, str):
        return []
    if isBase64(payload):
        try:
            payload = base64.b64decode(payload).decode('latin1')
        except:
            pass
    return [line.strip() for line in payload.split('\n') 
                if not line.strip()=='' and not line.startswith('>')]

def get_num_sentences(payload):
    try:
        return len(nltk.sent_tokenize(' '.join(extract_review(payload))))
    except:
        return None
    
def get_num_words(payload):
    return len(' '.join(extract_review(payload)).split())


lemmatizer = WordNetLemmatizer() 
def lemmatize(text):
    
    text = ' '.join(text)

    # Remove On Wed, Aug 28, 2019 at 10:33:46AM +0800, developer wrote:
    # This part does not have a certain structure across emails, 
    # thus the more general regex
    text = re.sub(r'On .*, .* wrote:', '', text)
    
    # Remove punctuation and numbers, switch to lowercase
    text = re.sub(r'[_\d,:+.!?\\-]+', ' ', text.lower())
    # lemmatize and return as one string
    return ' '.join(
                    [lemmatizer.lemmatize(word) for word in word_tokenize(text)]
                    )
