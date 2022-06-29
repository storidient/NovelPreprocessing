from pathlib import Path
import logging, re, argparse
from typing import List, Dict, Optional
from boltons.iterutils import pairwise
from utils import Rx, B

    

def clean_txt(line : str):
  """clean a string"""
  return line.replace('\n', '').replace(u'\xa0', u' ').strip()


def download(dir : str) -> List[str]:
  """Gets the directory of the file and returns the text"""
  with open(dir,  mode='rt', encoding='utf-8') as f:
    text = f.readlines()
  return list(map(clean_txt, text))


class RxLogging:
  """Gets the logger and monitors the process"""
  def __init__(self, logger):
    self.logger = logger
    self.show_key = list()
  
  def show(self, key: str):
    """Gets the show_key list updated"""
    self.show_key = [key] if type(key) == str else key
  
  def print(self, key : str, message : str):
    """Prints the message if the key is in the show_key list"""
    self.logger.info(message) if key in self.show_key else self.logger.debug(message)
  
  def check(self, keys : List[str], pattern: Dict[str, str]) -> List[str]:
    """Checks if the keys are in the pattern dictionary"""
    keys = keys if type(keys) == list else [keys]
    undefined = [key for key in keys if key not in pattern]
    if len(undefined):
      self.logger.warning('Undefined key : %s' % ('/'.join(undefined)))
    return list(set(keys)- set(undefined))


class RxDivision(RxLogging):
  """Divides the episodes and scenes"""
  def __init__(self, logger, ep_pattern : Optional[Dict[str, str]] = None, 
               scene_pattern : Optional[Dict[str, str]] = None):
    RxLogging.__init__(self, logger)
    self.pattern = dict()
    self.ep, self.scene = ep_pattern, scene_pattern

    if ep_pattern == None:
      from scripts import ep_pattern_dict
      self.ep = ep_pattern_dict
    if scene_pattern == None:
      from scripts import scene_pattern_dict
      self.scene = scene_pattern_dict
  
  def match(self, line : str) -> bool:
    """Returns True if the line matches with the pattern"""
    for key in self.pattern.keys():
      if re.match(self.pattern[key], line.lower()):
        self.print(key, 'seperation_pattern : %s / line : %s' % (key,line))
        return True      
      else: pass
    return False
      
  def main(self, text : List[str], scene : bool = False) -> List[str]:
    """Divides the text into episodes"""
    self.pattern = self.ep if scene == False else self.scene
    indices = [0] + [idx for idx, line in enumerate(text) if self.match(line) == True]
    
    if len(indices) == 1:
      return [text]
   
    else:
      output = [text[:s2] if (s1 == 0 and indices.count(0) == 1) else text[s1+1:s2] 
                for s1, s2 in pairwise(sorted(indices))]
      output.append(text[max(indices)+1:])  
      return [x for x in output if len(x) > 0]


class RxSetting:
  """Gets the revising rules and patterns easily"""
  def __init__(self, default : bool):
    from scripts import (default_dict, 
                         letter_dict, 
                         bracket_dict, 
                         unify_dict)
    
    self.pattern = default_dict if default == True else dict()
    self.letter_dict = letter_dict
    self.bracket_dict = bracket_dict
    self.unify_dict = unify_dict

    self.excluded_bracket = list()

  def update_letter(self, key_list : List[str]):
    """Gets the letters to delete and updates the revising rules"""
    self.pattern.update(
        {key : Rx('[%s]' % (self.letter_dict[key]), '', 1) for key in keys}
        )
  
  def update_bracket(self, input_key : List[str], output_key: str):
    """Gets the brackets to revise and updates the revising rules"""
    self.excluded_bracket = input_key

    for key in input_key:
      self.pattern.update(
          {key + '_open' :  Rx(self.bracket[key].open, 
                              self.bracket[output_key].open, 2),
          key + '_close' : Rx(self.bracket[key].close,
                              self.bracket[output_key].open, 2)})
    self._empty_bracket()
  
  def _empty_bracket(self):
    """Makes rules to delete empty brackets e.g. (), <> ..."""
    remain_keys = set(self.bracket.keys()) - set(self.excluded_bracket)
    for key in remain_keys:
      self.pattern.update(
          {'empty_'+ key : Rx('%s[^%s]*%s' % (self.bracket[key].open,
                                              self.bracket[key].close,
                                              self.bracket[key].close), '', 100)}
                          )
  
  def update_unify(self, keys : Optional[List[str]]):
    """Gets the special marks to unify and updates the revising rules"""
    keys = self.unify() if keys == None else keys
    self.pattern.update(
        {'unify_' + key : self.unify[key] for key in self.check(keys, self.unify)}
      )
  
  @cached_property
  def check(self) -> str:
    """Returns the RxPattern to check if lines have unexpected special marks"""
    output = ['\.', '\?', '\!', ' ', ',']
    
    output += [self.letter[key] for key in self._exclude(self.letter.keys())]
    output += [self.bracket[key].open + self.bracket[key].close
               for key in self._exclude(self.bracket, self.excluded_bracket)] 
    
    output += [self.pattern[key].outcome for key in self.pattern if key.startswith('unify_')] 
    return '[^%s]' % (''.join(set(output)))
  
  def _exclude(self, whole_keys : List[str], minus_keys : Optional[List[str]]):
    minus_keys = self.pattern.keys() if minus_keys == None else minus_keys
    return set(whole_keys) - set(minus_keys)

  
class RxRevision(RxLogging):
  """Gets the revising patterns and revise the text"""
  def __init__(self, logger, pattern):
    super().__init__(logger)
    self.pattern = pattern
    
  def ordering(self, keys):
    """Re-orders the revising rules by the level"""
    return sorted(keys, key = lambda x : self.pattern[x].level)

  def update_pattern(self, text):
    """Adds 「」『』 marks as quotation marks if there is no " in the text"""
    text = ''.join(text) if type(text) == list else text
    
    if re.match('.*["“”].*', text):
      self.pattern.pop('alternative_quotation', None)

    elif re.match('.*[「」『』].*', text):
      self.pattern.update({'alternative_quotation' : Rx('[「」『』]', '"', 0)})
      self.logger.info('Quotation_updated : 「」『』')
    
    elif re.match('.*[<>].*', text):
      self.pattern.update({'alternative_quotation' : Rx('[<>]', '"', 0)})
      self.logger.info('Quotation_updated : <>')
   
  def apply(self, key : str, input : str):
    """Applies the revsing rules to the line"""
    pattern = self.pattern[key]
    output = re.sub(pattern.target, pattern.outcome, input)
    if input != output:
      self.print(key,'pattern : %s / before %s / after %s' %(key, input, output))              
    return output

  def main(self, text):
    """Revises the text"""
    self.update_pattern(text)
    keys = self.ordering(self.pattern.keys())
    
    for key in keys:
      text = list(map(lambda x : self.apply(key, x), text))
      
    return [x for x in map(lambda line : re.sub(' +', ' ', line).strip(), text) if len(x) > 0]
    
