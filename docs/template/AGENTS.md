this is the final output, this is what the cookbook app uses: 
  
  The schema includes:                                                                       
  - All fields with types and descriptions                                                   
  - Conditional validation for quantity_kind (exact requires qty+unit, approximate allows   
  both or neither, unquantified forbids them)                                                
  - UUID pattern validation                                                                  
  - minLength, minimum, and default constraints matching the Zod schema 


  Pancakes.JSON is an example of a real recipe in my database, note how the ingridients are tied to a specific recipe step.
