import { PartialType } from '@nestjs/mapped-types';
import { CreateLanguageDto } from './create-language.dto.js';

export class UpdateLanguageDto extends PartialType(CreateLanguageDto) {}
