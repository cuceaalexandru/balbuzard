"""
bbcrack - v0.06 2013-04-02 Philippe Lagadec

bbcrack is a tool to crack malware obfuscation such as XOR, ROL, ADD (and
many combinations), by bruteforcing all possible keys and and checking for
specific patterns (IP addresses, domain names, URLs, known file headers and
strings, etc) using the balbuzard engine.
It is part of the Balbuzard package.

For more info and updates: http://www.decalage.info/balbuzard

usage: balbucrack [options] <file>


balbucrack is copyright (c) 2013, Philippe Lagadec (http://www.decalage.info)
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

 * Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
 * Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

__version__ = '0.06'

#------------------------------------------------------------------------------
# CHANGELOG:
# 2013-02-24 v0.01 PL: - 1st version, moved code from balbuzard
#                      - Transform classes instead of functions
# 2013-03-05 v0.02 PL: - progressive cracking: first simple/fast patterns on all
#                        cases, select best ones, then more elaborate patterns
# 2013-03-15 v0.03 PL: - harvest mode: run all transforms, extract all
#                        significant patterns
# 2013-03-21 v0.04 PL: - open file from password-protected zip (inspired from
#                        Didier Steven's pdfid, thanks Didier! :-)
# 2013-03-26 v0.05 PL: - switched from regex to multi-string patterns, 8x speed
#                        increase in harvest mode.
#                      - fixed bug in xor_add transform
# 2013-04-02 v0.06 PL: - added Transform_XOR_DEC


#------------------------------------------------------------------------------
#TODO
# + split harvest code to bbharvest
# + declare patterns only once in a separate module, use variables to create
#   groups for stage 1/2
# + profiling to see which patterns take more time => find which regex hangs
# + increase default params - k=30 s=5?
# + two stage regex, or string+regex, multiple strings, stop after 1 match
# + plugin dir to load user transforms and patterns (using exec or import?)
# + move main code to functions
# + test yara engine to see if faster
# + harvest mode: option to save copy of every matching file
# - merge regex of same weight to improve speed?
# - try acora for faster multi-string search, or other libraries?
# - try pyre2 for faster regex search?
# - option to launch balbuzard with bbcrack patterns only
# - distributed processing on several machines with slave processes
# - add patterns: file path Windows, Unix
# - performance improvement: use findall in Pattern rather than finditer?
#   OR even just find the 1st occurence?
# - inverse transform in each transform class? (useful in bbtrans)
# - option to run balbuzard automatically on best scores
# - csv output for stage1+2 or harvest mode
# - for some patterns such as e-mail, would be good to have a validation function
#   on top of regex to filter out false positives. for example using tldextract
#   or list of TLDs: http://data.iana.org/TLD/tlds-alpha-by-domain.txt.
# - optimize patterns with strings + case-insensitive (with lower())
# - Transforms: class method or attribute to return total number of params, to
#   be able to display progression as % or ETA.

# other transforms to be added:
# sub inc rol
# xor add rol
# xor rol add
# add xor rol
# base64
# hex
# split with two transforms
# xor chained with previous char



#--- IMPORTS ------------------------------------------------------------------

import sys, os, time, optparse, zipfile

# for sorting: see http://wiki.python.org/moin/HowTo/Sorting/
from operator import itemgetter, attrgetter

import balbuzard
from balbuzard import Pattern, Pattern_re


#--- CLASSES ------------------------------------------------------------------

class Transform_string (object):
    """
    Generic class to define a transform that acts on a string globally.
    """
    # generic name and id for the class:
    gen_name = 'Generic String Transform'
    gen_id   = 'string'

    def __init__(self, params=None):
        """
        constructor for the Transform object.
        This method needs to be overloaded for every specific Transform.
        It should set name and shortname according to the provided parameters.
        (for example shortname="xor_17" for a XOR transform with params=17)
        params: single value or tuple of values, parameters for the transformation
        """
        self.name = 'Undefined String Transform'
        self.shortname = 'undefined_string'
        self.params = params


    def transform_string (self, data):
        """
        Method to be overloaded, only for a transform that acts on a string
        globally.
        This method should apply the transform to the data string, using params
        as parameters, and return the transformed data as a string.
        (the resulting string does not need to have the same length as data)
        """
        raise NotImplementedError

    @staticmethod
    def iter_params ():
        """
        Method to be overloaded.
        This static method should iterate over all possible parameters for the
        transform function, yielding each set of parameters as a single value
        or a tuple of values.
        (for example for a XOR transform, it should yield 1 to 255)
        This method should be used on the Transform class in order to
        instantiate a Transform object with each set of parameters.
        """
        raise NotImplementedError

##    def iter_transform (self, data):
##        """
##        Runs the transform on data for all possible values of the parameters,
##        and yields the transformed data for each possibility.
##        """
##        for params in self.iter_params():
##            #print self.name
##            yield self.transform_string(data, params)


class Transform_char (Transform_string):
    """
    Generic class to define a transform that acts on each character of a string
    separately.
    """
    # generic name for the class:
    gen_name = 'Generic Character Transform'
    gen_id   = 'char'

    def __init__(self, params=None):
        """
        constructor for the Transform object.
        This method needs to be overloaded for every specific Transform.
        It should set name and shortname according to the provided parameters.
        (for example shortname="xor_17" for a XOR transform with params=17)
        params: single value or tuple of values, parameters for the transformation
        """
        self.name = 'Undefined Character Transform'
        self.shortname = 'undefined_char'
        self.params = params


    def transform_string (self, data):
        """
        This method applies the transform to the data string, using params
        as parameters, and return the transformed data as a string.
        Here, each character is transformed separately by calling transform_char.
        A translation table is used to speed up the processing.
        (the resulting string should have the same length as data)
        """
        # for optimal speed, we build a translation table:
        self.trans_table = ''
        for i in xrange(256):
            self.trans_table += self.transform_char(chr(i))
        return data.translate(self.trans_table)

    def transform_char (self, char):
        """
        Method to be overloaded, only for a transform that acts on a character.
        This method should apply the transform to the provided char, using params
        as parameters, and return the transformed data as a character.
        (here character = string of length 1)
        """
        raise NotImplementedError


#--- TRANSFORMS ---------------------------------------------------------------

class Transform_identity (Transform_string):
    """
    Transform that does not change data.
    """
    # generic name for the class:
    gen_name = 'Identity'
    gen_id   = 'ident'

    def __init__(self, params=None):
        self.name = "Identity Transformation"
        self.shortname = "identity"
        self.params = None

    def transform_string (self, data):
        return data

    @staticmethod
    def iter_params ():
        yield None


#------------------------------------------------------------------------------
class Transform_XOR (Transform_char):
    """
    XOR Transform
    """
    # generic name for the class:
    gen_name = 'XOR'
    gen_id   = 'xor'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>0 and params<256
        self.params = params
        self.name = "XOR %02X" % params
        self.shortname = "xor_%02X" % params

    def transform_char (self, char):
        # here params is an integer
        return chr(ord(char) ^ self.params)

    @staticmethod
    def iter_params ():
        # the XOR key can be 1 to 255 (0 would be identity)
        for key in xrange(1,256):
            yield key


#------------------------------------------------------------------------------
class Transform_XOR_INC (Transform_string):
    """
    XOR Transform, with incrementing key
    """
    # generic name for the class:
    gen_name = 'XOR INC'
    gen_id   = 'xor_inc'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>=0 and params<256
        self.params = params
        self.name = "XOR %02X INC" % params
        self.shortname = "xor%02X_inc" % params

    def transform_string (self, data):
        # here params is an integer
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        out = ''
        for i in xrange(len(data)):
            xor_key = (self.params + i) & 0xFF
            out += chr(ord(data[i]) ^ xor_key)
        return out

    @staticmethod
    def iter_params ():
        # the XOR key can be 0 to 255 (0 is not identity here)
        for xor_key in xrange(0,256):
            yield xor_key


#------------------------------------------------------------------------------
class Transform_XOR_DEC (Transform_string):
    """
    XOR Transform, with decrementing key
    """
    # generic name for the class:
    gen_name = 'XOR DEC'
    gen_id   = 'xor_dec'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>=0 and params<256
        self.params = params
        self.name = "XOR %02X DEC" % params
        self.shortname = "xor%02X_dec" % params

    def transform_string (self, data):
        # here params is an integer
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        out = ''
        for i in xrange(len(data)):
            xor_key = (self.params + 0xFF - i) & 0xFF
            out += chr(ord(data[i]) ^ xor_key)
        return out

    @staticmethod
    def iter_params ():
        # the XOR key can be 0 to 255 (0 is not identity here)
        for xor_key in xrange(0,256):
            yield xor_key


#------------------------------------------------------------------------------
class Transform_XOR_INC_ROL (Transform_string):
    """
    XOR Transform, with incrementing key, then ROL N bits
    """
    # generic name for the class:
    gen_name = 'XOR INC ROL'
    gen_id   = 'xor_inc_rol'

    def __init__(self, params):
        self.params = params
        self.name = "XOR %02X INC then ROL %d" % params
        self.shortname = "xor%02X_inc_rol%d" % params

    def transform_char (self, char):
        # here params is a tuple
        xor_key, rol_bits = self.params
        return chr(rol(ord(char) ^ xor_key, rol_bits))

    def transform_string (self, data):
        # here params is a tuple
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        xor_key_init, rol_bits = self.params
        out = ''
        for i in xrange(len(data)):
            xor_key = (xor_key_init + i) & 0xFF
            out += chr(rol(ord(data[i]) ^ xor_key, rol_bits))
        return out

    @staticmethod
    def iter_params ():
        "return (XOR key, ROL bits)"
        # the XOR key can be 0 to 255 (0 is not identity here)
        for xor_key in xrange(0,256):
            # the ROL bits can be 1 to 7:
            for rol_bits in xrange(1,8):
                yield (xor_key, rol_bits)


#------------------------------------------------------------------------------
class Transform_SUB_INC (Transform_string):
    """
    SUB Transform, with incrementing key
    """
    # generic name for the class:
    gen_name = 'SUB INC'
    gen_id   = 'sub_inc'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>=0 and params<256
        self.params = params
        self.name = "SUB %02X INC" % params
        self.shortname = "sub%02X_inc" % params

    def transform_string (self, data):
        # here params is an integer
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        out = ''
        for i in xrange(len(data)):
            key = (self.params + i) & 0xFF
            out += chr((ord(data[i]) - key) & 0xFF)
        return out

    @staticmethod
    def iter_params ():
        # the SUB key can be 0 to 255 (0 is not identity here)
        for key in xrange(0,256):
            yield key


def rol(byte, count):
    byte = (byte << count | byte >> (8-count)) & 0xFF
    return byte

###safety checks
##assert rol(1, 1) == 2
##assert rol(128, 1) == 1
##assert rol(1, 7) == 128
##assert rol(1, 8) == 1

#------------------------------------------------------------------------------
class Transform_XOR_Chained (Transform_string):
    """
    XOR Transform, chained with previous character.
    xor_chained(c[i], key) = c[i] xor c[i-1] xor key
    """
    # generic name for the class:
    gen_name = 'XOR Chained'
    gen_id   = 'xor_chained'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>=0 and params<256
        self.params = params
        self.name = "XOR %02X Chained" % params
        self.shortname = "xor%02X_chained" % params

    def transform_string (self, data):
        # here params is an integer
        #TODO: it would be much faster to do the xor_chained once, then all
        #      xor transforms using translate() only
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        if len(data) == 0: return ''
        xor_key = self.params
        # 1st char is just xored with key:
        out = chr(ord(data[0]) ^ xor_key)
        for i in xrange(1, len(data)):
            out += chr(ord(data[i]) ^ xor_key ^ ord(data[i-1]))
        return out

    @staticmethod
    def iter_params ():
        # the XOR key can be 0 to 255 (0 is not identity here)
        for xor_key in xrange(0,256):
            yield xor_key


#------------------------------------------------------------------------------
class Transform_XOR_RChained (Transform_string):
    """
    XOR Transform, chained with next character. (chained on the right)
    xor_rchained(c[i], key) = c[i] xor c[i+1] xor key
    """
    # generic name for the class:
    gen_name = 'XOR RChained'
    gen_id   = 'xor_rchained'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>=0 and params<256
        self.params = params
        self.name = "XOR %02X RChained" % params
        self.shortname = "xor%02X_rchained" % params

    def transform_string (self, data):
        # here params is an integer
        #TODO: it would be much faster to do the xor_rchained once, then all
        #      xor transforms using translate() only
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        if len(data) == 0: return ''
        out = ''
        xor_key = self.params
        # all chars except last one are xored with key and next char:
        for i in xrange(len(data)-1):
            out += chr(ord(data[i]) ^ xor_key ^ ord(data[i+1]))
        # last char is just xored with key:
        out += chr(ord(data[len(data)-1]) ^ xor_key)
        return out

    @staticmethod
    def iter_params ():
        # the XOR key can be 0 to 255 (0 is not identity here)
        for xor_key in xrange(0,256):
            yield xor_key


#------------------------------------------------------------------------------
class Transform_XOR_RChainedAll (Transform_string):
    """
    XOR Transform, chained from the right with all following characters.
    (as found in Taidoor malware)
    NOTE: this only works well in harvest mode, when testing all 256
          possibilities, because the key is position-dependent.
    xor_rchained_all(c[i], key) = c[i] xor key xor c[i+1] xor c[i+2]... xor c[N]
    """
    # generic name for the class:
    gen_name = 'XOR RChained All'
    gen_id   = 'xor_rchained_all'

    def __init__(self, params):
        assert isinstance(params, int)
        assert params>=0 and params<256
        self.params = params
        self.name = "XOR %02X RChained All" % params
        self.shortname = "xor%02X_rchained_all" % params

    def transform_string (self, data):
        # here params is an integer
        #TODO: it would be much faster to do the xor_rchained once, then all
        #      xor transforms using translate() only
        #TODO: use a list comprehension + join to get better performance
        # this loop is more readable, but likely to  be much slower
        if len(data) == 0: return ''
        xor_key = self.params
        # transform data string to list of integers:
        l = map(ord, data)
        # loop from last char to 2nd one:
        for i in xrange(len(data)-1, 1, -1):
            l[i-1] = l[i-1] ^ xor_key ^ l[i]
        # last char is only xored with key:
        l[len(data)-1] = l[len(data)-1] ^ xor_key
        # convert back to list of chars:
        l = map(chr, l)
        out = ''.join(l)
        return out

    @staticmethod
    def iter_params ():
        # the XOR key can be 0 to 255 (0 is not identity here)
        for xor_key in xrange(0,256):
            yield xor_key


#------------------------------------------------------------------------------
class Transform_XOR_ROL (Transform_char):
    """
    XOR+ROL Transform - first XOR, then ROL
    """
    # generic name for the class:
    gen_name = 'XOR then ROL'
    gen_id   = 'xor_rol'

    def __init__(self, params):
        self.params = params
        self.name = "XOR %02X then ROL %d" % params
        self.shortname = "xor%02X_rol%d" % params

    def transform_char (self, char):
        # here params is a tuple
        xor_key, rol_bits = self.params
        return chr(rol(ord(char) ^ xor_key, rol_bits))

    @staticmethod
    def iter_params ():
        "return (XOR key, ROL bits)"
        # the XOR key can be 1 to 255 (0 would be identity)
        for xor_key in xrange(1,256):
            # the ROL bits can be 1 to 7:
            for rol_bits in xrange(1,8):
                yield (xor_key, rol_bits)


#------------------------------------------------------------------------------
class Transform_ADD (Transform_char):
    """
    ADD Transform
    """
    # generic name for the class:
    gen_name = 'ADD'
    gen_id   = 'add'

    def __init__(self, params):
        self.params = params
        self.name = "ADD %02X" % params
        self.shortname = "add%02X" % params

    def transform_char (self, char):
        # here params is an integer
        add_key = self.params
        return chr((ord(char) + add_key) & 0xFF)

    @staticmethod
    def iter_params ():
        "return ADD key"
        # the ADD key can be 1 to 255 (0 would be identity):
        for add_key in xrange(1,256):
            yield add_key


#------------------------------------------------------------------------------
class Transform_ADD_ROL (Transform_char):
    """
    ADD+ROL Transform - first ADD, then ROL
    """
    # generic name for the class:
    gen_name = 'ADD then ROL'
    gen_id   = 'add_rol'

    def __init__(self, params):
        self.params = params
        self.name = "ADD %02X then ROL %d" % params
        self.shortname = "add%02X_rol%d" % params

    def transform_char (self, char):
        # here params is a tuple
        add_key, rol_bits = self.params
        return chr(rol((ord(char) + add_key) & 0xFF, rol_bits))

    @staticmethod
    def iter_params ():
        "return (ADD key, ROL bits)"
        # the ADD key can be 1 to 255 (0 would be identity)
        for add_key in xrange(1,256):
            # the ROL bits can be 1 to 7:
            for rol_bits in xrange(1,8):
                yield (add_key, rol_bits)


#------------------------------------------------------------------------------
class Transform_ROL_ADD (Transform_char):
    """
    ROL+ADD Transform - first ROL, then ADD
    """
    # generic name for the class:
    gen_name = 'ROL then ADD'
    gen_id   = 'rol_add'

    def __init__(self, params):
        self.params = params
        self.name = "ROL %d then ADD %02X" % params
        self.shortname = "rol%d_add%02X" % params

    def transform_char (self, char):
        # here params is a tuple
        rol_bits, add_key = self.params
        return chr((rol(ord(char), rol_bits) + add_key) & 0xFF)

    @staticmethod
    def iter_params ():
        "return (ROL bits, ADD key)"
        # the ROL bits can be 1 to 7:
        for rol_bits in xrange(1,8):
            # the ADD key can be 1 to 255 (0 would be identity)
            for add_key in xrange(1,256):
                yield (rol_bits, add_key)


#------------------------------------------------------------------------------
class Transform_XOR_ADD (Transform_char):
    """
    XOR+ADD Transform - first XOR, then ADD
    """
    # generic name for the class:
    gen_name = 'XOR then ADD'
    gen_id   = 'xor_add'

    def __init__(self, params):
        self.params = params
        self.name = "XOR %02X then ADD %02X" % params
        self.shortname = "xor%02X_add%02X" % params

    def transform_char (self, char):
        # here params is a tuple
        xor_key, add_key = self.params
        return chr(((ord(char) ^ xor_key) + add_key) & 0xFF)

    @staticmethod
    def iter_params ():
        "return (XOR key1, ADD key2)"
        # the XOR key can be 1 to 255 (0 would be identity)
        for xor_key in xrange(1,256):
            # the ADD key can be 1 to 255 (0 would be identity):
            for add_key in xrange(1,256):
                yield (xor_key, add_key)


#------------------------------------------------------------------------------
class Transform_ADD_XOR (Transform_char):
    """
    ADD+XOR Transform - first ADD, then XOR
    """
    # generic name for the class:
    gen_name = 'ADD then XOR'
    gen_id   = 'add_xor'

    def __init__(self, params):
        self.params = params
        self.name = "ADD %02X then XOR %02X" % params
        self.shortname = "add%02X_xor%02X" % params

    def transform_char (self, char):
        # here params is a tuple
        add_key, xor_key = self.params
        return chr(((ord(char) + add_key) & 0xFF) ^ xor_key)

    @staticmethod
    def iter_params ():
        "return (ADD key1, XOR key2)"
        # the ADD key can be 1 to 255 (0 would be identity):
        for add_key in xrange(1,256):
            # the XOR key can be 1 to 255 (0 would be identity)
            for xor_key in xrange(1,256):
                yield (add_key, xor_key)


#--- TRANSFORM GROUPS ---------------------------------------------------------

# Transforms level 1
transform_classes1 = [
    Transform_identity,
    Transform_XOR,
    Transform_ADD,
    Transform_XOR_ROL,
    Transform_ADD_ROL,
    Transform_ROL_ADD,
    ]

# Transforms level 2
transform_classes2 = transform_classes1 + [
    Transform_XOR_ADD,
    Transform_ADD_XOR,
    Transform_XOR_INC,
    Transform_XOR_DEC,
    Transform_SUB_INC,
    Transform_XOR_Chained,
    Transform_XOR_RChained,
    Transform_XOR_RChainedAll,
    ]

# Transforms level 3
transform_classes3 = transform_classes2 + [
    Transform_XOR_INC_ROL,
    ]


#--- PATTERNS -----------------------------------------------------------------

# simple patterns for initial, fast filtering of best candidates
# (only used for counting - avoid regex)
bbcrack_patterns_stage1 = [
    Pattern('spaces', ' '),
    Pattern('nulls', '\x00'),
    Pattern('newlines', '\x0D\x0A', weight=100),
    Pattern('spaces blob', ' '*32, weight=100),
    Pattern('nulls blob', '\x00'*32, weight=100),
    Pattern('http URL start', 'http://', weight=10000),
    Pattern('https URL start', 'https://', weight=10000),
    Pattern('ftp URL start', 'ftp://', weight=10000),
    Pattern('EXE PE section', ['.text', '.data', '.rsrc'], weight=10000),
    Pattern("EXE PE DOS message", "This program cannot be run in DOS mode", nocase=True, weight=100000),
    ]


# specific patterns for cracking (simpler than Balbuzard, for speed):
# Here it's better to be simple and fast than accurate
bbcrack_patterns = [
##    Pattern('Whitespaces and newline characters', regex=r'\s+'),
##    Pattern('Null characters', regex=r'\000+'),
    Pattern_re('Any word longer than 6 chars', r'\b[A-Za-z]{6,}\b'),
    Pattern_re('Sentence of 3 words or more', r'([A-Za-z]{2,}\s){2,}[A-Za-z]{2,}', weight=1), #TODO: this one seems incomplete
##    Pattern("IP addresses", regex=r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", weight=100),
    Pattern_re("IP address", r"(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])", weight=100),
    Pattern_re('URL (http/https/ftp)', r'(http|https|ftp)\://[a-zA-Z0-9\-\.&%\$#\=~]+', weight=100),
    Pattern_re('e-mail address', r'(?i)\b[A-Z0-9._%+-]+@(?:[A-Z0-9-]+\.)+(?:[A-Z]{2}|com|org|net|edu|gov|mil|int|biz|info|mobi|name|aero|asia|jobs|museum)\b', weight=10), # adapted from http://www.regular-expressions.info/email.html
##    Pattern('e-mail address', regex=r'([a-zA-Z0-9_-]+\.)*[a-zA-Z0-9_-]+@([a-zA-Z0-9_-]+\.)+[a-zA-Z0-9_-]+', weight=10),
    #Pattern('domain name', regex=r'', weight=10),
    Pattern_re('CamelCase word', r'\b([A-Z][a-z0-9]{2,}){2,}\b', weight=1),
    Pattern_re("EXE MZ followed by PE", r"(?s)MZ.{32,1024}PE\000\000", weight=100), # (?s) sets the DOTALL flag, so that dot matches any character
    Pattern("EXE PE DOS message", "This program cannot be run in DOS mode", nocase=True, weight=10000),
    Pattern_re('Hex blob', r'([A-F0-9][A-F0-9]|[a-f0-9][a-f0-9]){16,}', weight=1),
    Pattern_re('Base64 blob', r'(?:[A-Za-z0-9+/]{4}){2,}(?:[A-Za-z0-9+/]{2}[AEIMQUYcgkosw048]=|[A-Za-z0-9+/][AQgw]==)', weight=1),
    Pattern("EXE: section name", ".text|.data|.rdata|.rsrc".split('|'), nocase=True, weight=100), #nocase?
    Pattern("Possible OLE2 header (D0CF)", "\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", weight=10),
]

harvest_patterns = [
    Pattern_re("IP address", r"\b(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\b", weight=100),
    Pattern_re('URL (http/https/ftp)', r'(http|https|ftp)\://[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,3}(:[a-zA-Z0-9]*)?/?([a-zA-Z0-9\-\._\?\,\'/\\\+&amp;%\$#\=~])*[^\.\,\)\(\s]', weight=10),
##    Pattern('e-mail address', regex=r'([a-zA-Z0-9]+([\.+_-][a-zA-Z0-9]+)*)@(([a-zA-Z0-9]+((\.|[-]{1,2})[a-zA-Z0-9]+)*)\.[a-zA-Z]{2,6})', weight=10), # source: http://regexlib.com/REDetails.aspx?regexp_id=2119
    Pattern_re('e-mail address', r'(?i)\b[A-Z0-9._%+-]+@(?:[A-Z0-9-]+\.)+(?:[A-Z]{2}|com|org|net|edu|gov|mil|int|biz|info|mobi|name|aero|asia|jobs|museum)\b', weight=10), # adapted from http://www.regular-expressions.info/email.html
    Pattern_re('domain name', r'(?=^.{1,254}$)(^(?:(?!\d+\.|-)[a-zA-Z0-9_\-]{1,63}(?<!-)\.?)+(?:[a-zA-Z]{2,})$)', weight=10), # source: http://regexlib.com/REDetails.aspx?regexp_id=1319
    Pattern_re("EXE MZ followed by PE", r"(?s)MZ.{32,1024}PE\000\000", weight=100), # (?s) sets the DOTALL flag, so that dot matches any character
    Pattern_re("Executable filename", r"\b\w+\.(EXE|COM|VBS|JS|VBE|JSE|BAT|CMD|DLL|SCR)\b", nocase=True, weight=10),
    Pattern("EXE: UPX header", "UPX"),
    Pattern("EXE: section name", ".text|.data|.rdata|.rsrc".split('|'), nocase=True, weight=10), #nocase?
    Pattern("EXE: packed with Petite", ".petite", nocase=True, weight=10), #nocase?
    Pattern("EXE: interesting Win32 function names", "WriteFile|IsDebuggerPresent|RegSetValue|CreateRemoteThread".split('|'), weight=10000),  #nocase?
    Pattern("EXE: interesting WinSock function names", "WS2_32.dll|WSASocket|WSASend|WSARecv".split('|'), nocase=True, weight=10000), #nocase?
    Pattern("EXE: possibly compiled with Microsoft Visual C++", "Microsoft Visual C++", weight=10000),

    Pattern("Interesting registry keys", "CurrentVersion\\Run|UserInit".split('|'), weight=10000), #nocase?
    Pattern("Interesting file names", "\\drivers\\etc\\hosts|cmd\.exe|\\Start Menu\\Programs\\Startup".split('|'), nocase=True, weight=10000),
    Pattern("Interesting keywords", "password|login|pwd|administrator|admin|root|smtp|pop|ftp|ssh|icq|backdoor|vmware".split('|'), nocase=True, weight=100), # removed http
    #Pattern_re("NOP instructions (possible shellcode)", r"\x90{4,}"), # this regex matches 4 NOPs or more

    Pattern("Possible OLE2 header (D0CF)", "\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", weight=10),
    Pattern("Possible VBA macros", "VBA"), #nocase?

    Pattern('Possible Flash header', 'SWF|FWS'.split('|')),
    Pattern('Flash OLE object 1', 'ShockwaveFlash.ShockwaveFlash', weight=10),
    Pattern('Flash OLE object 2', 'S\x00h\x00o\x00c\x00k\x00w\x00a\x00v\x00e\x00F\x00l\x00a\x00s\x00h', weight=10), # warning: this is unicode

    Pattern('Possible PDF header', '%PDF-', weight=10),
    Pattern('Possible PDF end of file marker', '%EOF', weight=10),

##    Pattern_re('Hex blob', r'([A-F0-9][A-F0-9]|[a-f0-9][a-f0-9]){16,}', weight=1),
##    Pattern_re('Base64 blob', r'(?:[A-Za-z0-9+/]{4}){2,}(?:[A-Za-z0-9+/]{2}[AEIMQUYcgkosw048]=|[A-Za-z0-9+/][AQgw]==)', weight=1),
]


#--- FUNCTIONS ----------------------------------------------------------------

def multi_trans (raw_data, transform_classes, profiling=False):
    """
    apply all transforms to raw_data, and extract all patterns of interest
    (Slow, but useful when a file uses multiple transforms.)
    """
    print '*** WARNING: harvest mode may return a lot of false positives!'
    # here we only want to extract patterns of interest
    bbz = balbuzard.Balbuzard(harvest_patterns)
    if not profiling:
        for Transform_class in transform_classes:
            # iterate over all possible params for that transform class:
            for params in Transform_class.iter_params():
                # instantiate a Transform object with these params
                transform = Transform_class(params)
                msg = 'transform %s          \r' % transform.shortname
                print msg,
                # transform data:
                data = transform.transform_string(raw_data)
                # search each pattern in transformed data:
                for pattern, matches in bbz.scan(data):
                    for index, match in matches:
                        if len(match)>3:
                            print '%s: %s at index %X, string=%s' % (
                                transform.shortname, pattern.name, index, repr(match))
        print '                                      '
    else:
        # same code, with profiling:
        count_trans = 0
        count_patterns = 0
        start_time = time.clock()
        for Transform_class in transform_classes:
            # iterate over all possible params for that transform class:
            for params in Transform_class.iter_params():
                count_trans += 1
                # instantiate a Transform object with these params
                transform = Transform_class(params)
                msg = 'transform %s          \r' % transform.shortname
                print msg,
                # transform data:
                start_trans = time.clock()
                data = transform.transform_string(raw_data)
                transform.time = time.clock()-start_trans
                # search each pattern in transformed data:
                for pattern, matches in bbz.scan_profiling(data):
                    count_patterns += 1
                    for index, match in matches:
                        if len(match)>3:
                            print '%s: %s at index %X, string=%s' % (
                                transform.shortname, pattern.name, index, repr(match))
                if count_trans % 10 == 0:
                    t = time.clock()-start_time
                    print 'PROFILING: %d transforms in %.1fs, %.2f ms/trans' % (
                        count_trans, t, t*1000/count_trans)
                    for pattern in sorted(bbz.patterns, key=attrgetter('total_time'),
                        reverse=True):
                        print '- %s: %.1f%%, total time = %.1fs' % (
                            pattern.name, 100*pattern.total_time/t,
                            pattern.total_time)
        print '                                      '



#=== MAIN =====================================================================

if __name__ == '__main__':

    usage = 'usage: %prog [options] <filename>'
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('-l', '--level', dest='level', type='int', default=2,
        help='select transforms level 1, 2 or 3')
    parser.add_option('-k', '--keep', dest='keep', type='int', default=20,
        help='number of transforms to keep after stage 1')
    parser.add_option('-s', '--save', dest='save', type='int', default=10,
        help='number of transforms to save to files after stage 2')
    parser.add_option("-t", "--transform", dest='transform', type='str', default=None,
        help='only check specific transforms (comma separated list, or "-t list" to display all available transforms)')
    parser.add_option("-m", action="store_true", dest="multitrans",
        help='harvest mode: will apply all transforms and extract patterns of interest. Slow, but useful when a file uses multiple transforms.')
    parser.add_option("-z", "--zip", dest='zip_password', type='str', default=None,
        help='if the file is a zip archive, open first file from it, using the provided password (requires Python 2.6+)')
    parser.add_option("-p", action="store_true", dest="profiling",
        help='profiling: measure time spent on each pattern.')

    (options, args) = parser.parse_args()

    # if option "-t list", display list of transforms and quit:
    if options.transform == 'list':
        print 'Available transforms:'
        for Transform in transform_classes3:
            print '- %s: %s' % (Transform.gen_id, Transform.gen_name)
        sys.exit()

    # Print help if no argurments are passed
    if len(args) == 0:
        print __doc__
        parser.print_help()
        sys.exit()

    fname = args[0]
    if options.zip_password is not None:
        # extract 1st file from zip archive, using password
        pwd = options.zip_password
        print 'Opening zip archive %s with password "%s"' % (fname, pwd)
        z = zipfile.ZipFile(fname, 'r')
        print 'Opening first file:', z.infolist()[0].filename
        raw_data = z.read(z.infolist()[0], pwd)
    else:
        # normal file
        print 'Opening file', fname
        f = file(fname, 'rb')
        raw_data = f.read()
        f.close()

    if   options.level == 1:
        transform_classes = transform_classes1
    elif options.level == 2:
        transform_classes = transform_classes2
    else:
        transform_classes = transform_classes3

    if options.transform:
        # options.transform is either a transform name, or a comma-separated list
        transform_classes = []
        trans_names = options.transform.split(',')
        for tname in trans_names:
            for trans in transform_classes3:
                if trans.gen_id == tname:
                    transform_classes.append(trans)
        # check if any transform was found:
        if len(transform_classes) == 0:
            sys.exit('Transform "%s" does not exist. Use "-t list" to see all available transforms.' % options.transform)

    if options.multitrans:
        # harvest mode, for multiple transformations
        multi_trans(raw_data, transform_classes, profiling=options.profiling)
        sys.exit()

    # STAGE 1: quickly count some significant characters to select best transforms
    print 'STAGE 1: quickly counting simple patterns for all transforms'
    results1 = []
    best_score = 0
    start_time = time.clock()
    bbz1 = balbuzard.Balbuzard(bbcrack_patterns_stage1)
    for Transform_class in transform_classes:
        # iterate over all possible params for that transform class:
        for params in Transform_class.iter_params():
            # instantiate a Transform object with these params
            transform = Transform_class(params)
            # transform data:
            data = transform.transform_string(raw_data)
            score = 0
            # search each pattern in transformed data:
            for pattern, count in bbz1.count(data):
                score += count*pattern.weight
##                print 'Found %d * %s weight=%d' % (
##                    count, pattern.name, pattern.weight)
            msg = '\rTransform %s: stage 1 score=%d          ' % (transform.shortname, score)
            print msg,
##            spaces = data.count(' ')
##            nulls = data.count('\x00')
##            newlines = data.count('\x0D\x0A')
##            pe = data.count('PE')
##            mz = data.count('MZ')
##            dos = data.count("This program cannot be run in DOS mode")
##            score = spaces + nulls + newlines*100 + pe*100 + mz*100 + dos*10000
##            print 'Transform %s: score=%d, spaces=%s, nulls=%d, newlines=%d' % (
##                transform.name, score, spaces, nulls, newlines)
            results1.append((transform, score))
            if score >= best_score:
                best_score = score
                print '\rBest score so far: %s, stage 1 score=%d' % (transform.shortname, score)
    print ''
    t = time.clock()-start_time
    print 'Checked %d transforms in %f seconds - %f transforms/s' % (
        len(results1), t, len(results1)/t)
    # sort transform results by score:
    results1 = sorted(results1, key=lambda r:r[1], reverse=True)
    # keep only the N best scores:
    results1 = results1[:options.keep]
    print '\nTOP %d SCORES stage 1:' % options.keep
    for res in results1:
        print res[0].shortname, res[1]
##    raw_input()

    # STAGE 2: search patterns on selected transforms
    results = []
    bbz = balbuzard.Balbuzard(bbcrack_patterns) #balbuzard.patterns) #
##    bbz.add_pattern('CamelCase word', regex=r'([A-Z][a-z0-9]{2,}){2,}', weight=10)
##    bbz.add_pattern('Any word longer than 5 chars', regex=r'[A-Za-z]{5,}')
##    bbz.add_pattern('Sentence of 3 words or more', regex=r'([A-Za-z]{2,}\s){2,}[A-Za-z]{2,}', weight=1)
##    bbz.add_pattern('URL (http/https/ftp)', regex=r'(http|https|ftp)\://[a-zA-Z0-9\-\.&%\$#\=~]+', weight=1000)


    for transform, score1 in results1:
        # transform data again (data was not kept)
        data = transform.transform_string(raw_data)
        score = 0
        for pattern, matches in bbz.scan(data):
            for index, match in matches:
##                    print 'Found %s at index %X, length=%d * weight=%d' % (
##                        pattern.name, index, len(match), pattern.weight)
                score += len(match)*pattern.weight
            print 'Found %d * %s weight=%d' % (
                len(matches), pattern.name, pattern.weight)
        print 'Transform %s: score=%d\n' % (transform.shortname, score)
        results.append((transform, score, data))

    print '\nHIGHEST SCORES:'
    results = sorted(results, key=lambda x: x[1], reverse=True)
    # take the best N:
    for transform, score, data in results[:options.save]:
        print '%s: score %d' % (transform.shortname, score)
        base, ext = os.path.splitext(fname)
        fname_trans = base+'_'+transform.shortname+ext
        print 'saving to file', fname_trans
        open(fname_trans, 'wb').write(data)



# This was coded while listening to The Walkmen "Heaven".